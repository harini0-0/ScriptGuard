"""Suite B: how faithfully digital PDFs and scans are read, measured on the medication lines.
Ground truth = the source lines of the hand-verified extractions (typed text)."""
import json
import re
import sys
import time
from difflib import SequenceMatcher
from metrics import DATA, KEY, REPORTS, realworld

realworld.patch_ocr_rotation()                    # same OCR path as the product's intake
from scriptguard.ingest import to_text           # noqa: E402

MOCKS = json.loads((DATA / "mocks.json").read_text())


def norm(s):
    """Lowercase, collapse spaces, ignore leading bullets/numbering ("- ", "• ", "3. ")."""
    s = re.sub(r"^\s*(?:[-•*]+|\d+[.)])\s*", "", (s or "").strip())
    return re.sub(r"\s+", " ", s.lower())


def nums(s):
    return re.findall(r"\d+(?:\.\d+)?", s or "")


def best_line(gt, lines):
    g = norm(gt)
    best, score = None, 0.0
    for l in lines:
        r = SequenceMatcher(None, g, norm(l)).ratio()
        if r > score:
            best, score = l, r
    return best, score


def run(formats=("pdf", "scan")):
    out = {}
    for fmt in formats:
        rows = []
        for case in sorted(KEY):
            folder = DATA / fmt / case
            if not folder.exists():
                continue
            for d in ("discharge_summary", "prescription"):
                f = next((p for p in folder.iterdir() if p.stem == d), None)
                if f is None:
                    continue
                t0 = time.time()
                doc = to_text(f)
                secs = time.time() - t0
                lines = [l for l in doc["text"].splitlines() if l.strip()]
                for med in MOCKS[case][d]:
                    gt = med["source_text"]
                    line, score = best_line(gt, lines)
                    exact = line is not None and norm(line) == norm(gt)
                    numbers_ok = line is not None and nums(gt) == nums(line)
                    rows.append({"case": case, "doc": d, "method": doc["method"], "gt": gt, "ocr": line,
                                 "similarity": round(score, 3), "exact": exact, "numbers_exact": numbers_ok,
                                 "found": score >= 0.92 and numbers_ok, "doc_seconds": round(secs, 2)})
        n = len(rows)
        docs_secs = {(r["case"], r["doc"]): r["doc_seconds"] for r in rows}
        out[fmt] = {"medication_lines": n,
                    "line_exact_match": sum(r["exact"] for r in rows) / n if n else None,
                    "line_found_ge_0.92_and_numbers_exact": sum(r["found"] for r in rows) / n if n else None,
                    "dose_numbers_exact": sum(r["numbers_exact"] for r in rows) / n if n else None,
                    "mean_char_similarity": sum(r["similarity"] for r in rows) / n if n else None,
                    "approx_char_error_rate": 1 - sum(r["similarity"] for r in rows) / n if n else None,
                    "seconds_per_document": sum(docs_secs.values()) / len(docs_secs) if docs_secs else None,
                    "methods": sorted({r["method"] for r in rows}),
                    "worst_lines": sorted(rows, key=lambda r: r["similarity"])[:5]}
        (REPORTS / f"suite_b_ocr_fidelity_{fmt}.json").write_text(json.dumps({"summary": out[fmt], "rows": rows}, indent=2))
    return out


def recompute(fmt):
    """Re-score saved readings (no OCR rerun)."""
    f = REPORTS / f"suite_b_ocr_fidelity_{fmt}.json"
    d = json.loads(f.read_text()); rows = d["rows"]
    for r in rows:
        r["similarity"] = round(SequenceMatcher(None, norm(r["gt"]), norm(r["ocr"])).ratio(), 3) if r["ocr"] else 0.0
        r["exact"] = r["ocr"] is not None and norm(r["ocr"]) == norm(r["gt"])
        r["found"] = r["similarity"] >= 0.92 and r["numbers_exact"]
    n = len(rows); sm = d["summary"]
    sm.update({"line_exact_match": sum(r["exact"] for r in rows) / n,
               "line_found_ge_0.92_and_numbers_exact": sum(r["found"] for r in rows) / n,
               "mean_char_similarity": sum(r["similarity"] for r in rows) / n,
               "approx_char_error_rate": 1 - sum(r["similarity"] for r in rows) / n,
               "worst_lines": sorted(rows, key=lambda r: r["similarity"])[:5]})
    f.write_text(json.dumps(d, indent=2))
    return sm


if __name__ == "__main__":
    fm = tuple(sys.argv[1:]) or ("pdf", "scan")
    res = run(fm)
    for k, v in res.items():
        print(k, json.dumps({a: b for a, b in v.items() if a != "worst_lines"}, indent=1))
