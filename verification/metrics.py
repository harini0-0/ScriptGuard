"""Shared paths and scoring for ScriptGuard verification. Reads the product code; never modifies it.

Definitions (high-severity flags are the ones that hold an order; low flags are advisory):
  planted error   an entry in data/answer_key.json
  caught (TP)     a high flag with the same type and the same medicine (after brand/generic normalization)
  missed (FN)     a planted error with no matching high flag
  false alarm(FP) a high flag that matches no planted error
  error recall    TP / (TP + FN)
  precision       TP / (TP + FP)
  F1              2 * precision * recall / (precision + recall)
  specificity     clean cases with no high flag and not sent to review / all clean cases
  review rate     cases routed to "check by hand" (NEEDS_REVIEW) / all cases
  case accuracy   cases fully right (all planted errors caught and no false alarms; clean cases passed) / all cases
"""
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRODUCT = Path(os.environ.get("SCRIPTGUARD_PRODUCT", HERE.parent)).resolve()
ENGINE = PRODUCT / "scriptguard2" / "engine"
HOST = PRODUCT / "sg2_host"
DATA = HERE / "data"
REPORTS = HERE / "reports"
REPORTS.mkdir(exist_ok=True)
sys.path.insert(0, str(ENGINE))

import realworld  # noqa: E402  (patches the engine exactly as the product does)
from scriptguard.pipeline import check_extraction  # noqa: E402

TYPE_MAP = {"stopped_in_summary_but_prescribed": "stopped_but_ordered",
            "missing_from_prescription": "missing_from_orders"}
KEY = json.loads((DATA / "answer_key.json").read_text())
EXCLUDED = {"case_005"}   # needs the home medication list (third document): reported, not scored


def run_checks(case_id, docs, raw):
    """docs: {doc_type: {text, method, low_confidence_numbers, file}}; raw: {doc_type: [meds]} (unnormalized)."""
    ex = {"case_id": case_id, "documents": {k: dict(docs[k], medications=raw[k]) for k in docs}}
    evidence = json.loads((ENGINE / "evidence.json").read_text())
    return realworld.build_flags(check_extraction(ex, evidence_db=evidence), raw, docs)


def score_case(case_id, result, seconds=None):
    expected = {(e["type"], realworld.canonical(e["drug"])) for e in KEY[case_id]["expected"]}
    high = [f for f in result["flags"] if f["severity"] == "HIGH"]
    found = {(TYPE_MAP.get(f["type"], f["type"]), realworld.canonical(f["drug"]) or f["drug"]) for f in high}
    found |= {(TYPE_MAP.get(f["type"], f["type"]), f["drug"]) for f in high}
    tp = {e for e in expected if e in found}
    fn = expected - tp
    matched = set()
    for f in high:
        keys = {(TYPE_MAP.get(f["type"], f["type"]), realworld.canonical(f["drug"]) or f["drug"]),
                (TYPE_MAP.get(f["type"], f["type"]), f["drug"])}
        if keys & expected:
            matched.add(id(f))
    fp = [f for f in high if id(f) not in matched]
    status = result["status"]
    clean = not expected
    correct = (status != "NEEDS_REVIEW" and not fp and not high) if clean else (not fn and not fp)
    return {"case": case_id, "scenario": KEY[case_id]["scenario"], "expected": sorted(map(list, expected)),
            "caught": sorted(map(list, tp)), "missed": sorted(map(list, fn)),
            "false_alarms": [[TYPE_MAP.get(f["type"], f["type"]), f["drug"]] for f in fp],
            "low_flags": [[f["type"], f["drug"]] for f in result["flags"] if f["severity"] == "LOW"],
            "status": status, "expected_status": "CLEAN" if clean else "HELD", "correct": correct,
            "review_reason": result.get("review_reason"), "seconds": seconds, "note": KEY[case_id].get("note", "")}


def summarize(rows, label):
    scored = [r for r in rows if r["case"] not in EXCLUDED and "error" not in r]
    tp = sum(len(r["caught"]) for r in scored)
    fn = sum(len(r["missed"]) for r in scored)
    fp = sum(len(r["false_alarms"]) for r in scored)
    clean = [r for r in scored if r["expected_status"] == "CLEAN"]
    spec_ok = sum(1 for r in clean if not r["false_alarms"] and r["status"] != "NEEDS_REVIEW")
    recall = tp / (tp + fn) if tp + fn else None
    precision = tp / (tp + fp) if tp + fp else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    per_type = defaultdict(lambda: {"planted": 0, "caught": 0})
    for r in scored:
        for t, _ in r["expected"]:
            per_type[t]["planted"] += 1
        for t, _ in r["caught"]:
            per_type[t]["caught"] += 1
    confusion = Counter((r["expected_status"], r["status"]) for r in scored)
    secs = [r["seconds"] for r in scored if r.get("seconds") is not None]
    return {
        "suite": label, "cases_scored": len(scored), "cases_excluded": sorted(EXCLUDED & {r["case"] for r in rows}),
        "errors_planted": tp + fn, "errors_caught": tp, "errors_missed": fn, "false_alarms": fp,
        "error_recall": recall, "precision": precision, "f1": f1,
        "clean_cases": len(clean), "specificity": spec_ok / len(clean) if clean else None,
        "false_alarms_per_case": fp / len(scored) if scored else None,
        "review_rate": sum(r["status"] == "NEEDS_REVIEW" for r in scored) / len(scored) if scored else None,
        "case_accuracy": sum(r["correct"] for r in scored) / len(scored) if scored else None,
        "advisory_low_flags": sum(len(r["low_flags"]) for r in scored),
        "per_type": dict(per_type),
        "status_confusion": {f"{a} -> {b}": n for (a, b), n in sorted(confusion.items())},
        "seconds_per_case": sum(secs) / len(secs) if secs else None,
        "errors": [r["case"] for r in rows if "error" in r],
    }


def save(name, summary, rows):
    (REPORTS / f"{name}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"
