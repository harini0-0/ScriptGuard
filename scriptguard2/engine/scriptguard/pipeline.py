"""Two stages, each usable on its own:

  Stage 1  extract_case(case_dir) -> extraction dict    (documents -> text -> medications)
  Stage 2  check_extraction(extraction) -> result dict   (grounding + comparison -> decision)

A case folder holds discharge_summary.* and prescription.* (home_medications.* optional),
where * is .pdf (digital or scanned), .png, .jpg, .jpeg, .tif, or .txt.
"""
import json
import os
from pathlib import Path

from .compare import compare
from .ground import ground
from .ingest import find_document, to_text
from .schema import normalize_med, to_number

REQUIRED_DOCS = ("discharge_summary", "prescription")
OPTIONAL_DOCS = ("home_medications",)
EVIDENCE_FILE = os.environ.get("SCRIPTGUARD_EVIDENCE", "evidence.json")
CHECKS_RUN = ["grounding (every value traced to the document)", "OCR confidence on doses",
              "dose mismatch", "stopped but still prescribed", "missing from prescription"]


# ---------------- Stage 1: extraction ----------------
def extract_case(case_dir, extractor=None):
    if extractor is None:
        from .extract import extract as extractor
    case_dir = Path(case_dir)
    documents = {}
    for doc_type in REQUIRED_DOCS + OPTIONAL_DOCS:
        path = find_document(case_dir, doc_type)
        if path is None:
            if doc_type in REQUIRED_DOCS:
                raise FileNotFoundError(f"{case_dir.name}: no {doc_type} file (.pdf/.png/.jpg/.txt) found")
            continue
        doc = to_text(path)
        doc["medications"] = extractor(doc["text"], doc_type)
        documents[doc_type] = doc
    return {"case_id": case_dir.name, "documents": documents}


# ---------------- Stage 2: checking ----------------
def _ocr_doubts(meds, low_conf, doc_label):
    doubts = []
    for m in meds:
        if m.get("dose") is None:
            continue
        for w in (x["word"] for x in low_conf):
            if to_number(w) == to_number(m["dose"]) and w in m.get("source_text", ""):
                doubts.append({"type": "grounding_failed", "drug": m["drug"],
                               "detail": f"{doc_label}: dose '{w}' read with low OCR confidence",
                               "source_text": m["source_text"]})
                break
    return doubts


def decide_status(conflicts):
    if any(c["type"] != "grounding_failed" for c in conflicts):
        return "HELD"            # mismatch found -> flagged for pharmacist review
    if conflicts:
        return "NEEDS_REVIEW"    # could not read some values reliably
    return "CLEAN"               # no discrepancies found by the checks run


STATUS_MESSAGE = {
    "HELD": "Flagged for pharmacist review: medication mismatch found",
    "NEEDS_REVIEW": "Needs human review: some values could not be read reliably",
    "CLEAN": "No discrepancies found by the checks run",
}


def check_extraction(extraction, evidence_db=None):
    docs = extraction["documents"]
    s, p = docs["discharge_summary"], docs["prescription"]
    s_meds = [normalize_med(m) for m in s["medications"]]
    p_meds = [normalize_med(m) for m in p["medications"]]

    failures = (ground(s_meds, s["text"], "discharge summary") + ground(p_meds, p["text"], "prescription")
                + _ocr_doubts(s_meds, s.get("low_confidence_numbers", []), "discharge summary")
                + _ocr_doubts(p_meds, p.get("low_confidence_numbers", []), "prescription"))
    bad = {f["drug"] for f in failures}
    conflicts = compare([m for m in s_meds if m["drug"] not in bad], [m for m in p_meds if m["drug"] not in bad])
    all_conflicts = conflicts + failures

    if evidence_db is None:
        ev = Path(EVIDENCE_FILE)
        evidence_db = json.loads(ev.read_text()) if ev.exists() else {}
    evidence = "; ".join(evidence_db[c["drug"]] for c in conflicts if c["drug"] in evidence_db) or None

    status = decide_status(all_conflicts)
    return {
        "case_id": extraction["case_id"],
        "status": status,
        "message": STATUS_MESSAGE[status],
        "conflicts": all_conflicts,
        "evidence": evidence,
        "checks_run": CHECKS_RUN,
        "extracted": {"summary": s_meds, "orders": p_meds},
        "ingest": {k: {"file": v["file"], "method": v["method"],
                       "low_confidence_numbers": v.get("low_confidence_numbers", [])} for k, v in docs.items()},
    }


# ---------------- Both stages (what the agent calls) ----------------
def run_case(case_dir, extracted_dir="extracted", results_dir="results", extractor=None):
    extraction = extract_case(case_dir, extractor)
    Path(extracted_dir).mkdir(parents=True, exist_ok=True)
    (Path(extracted_dir) / f"{extraction['case_id']}.json").write_text(json.dumps(extraction, indent=2))
    result = check_extraction(extraction)
    Path(results_dir).mkdir(parents=True, exist_ok=True)
    (Path(results_dir) / f"{result['case_id']}.json").write_text(json.dumps(result, indent=2))
    return result
