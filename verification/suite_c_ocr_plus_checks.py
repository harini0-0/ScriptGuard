"""Suite C: does OCR noise change the verdict? Verified extractions are re-pointed to the line OCR actually
produced (garbled text is kept as-is; a line OCR lost drops that medicine). No model involved."""
import json
import sys
import time
from metrics import DATA, KEY, realworld, run_checks, score_case, summarize, save
from suite_b_ocr_fidelity import best_line, nums

realworld.patch_ocr_rotation()
from scriptguard.ingest import to_text  # noqa: E402

MOCKS = json.loads((DATA / "mocks.json").read_text())


def realign(med, lines):
    line, score = best_line(med["source_text"], lines)
    if line is None or score < 0.6:
        return None                                    # OCR lost this line
    m = dict(med, source_text=line)
    ocr_nums = nums(line)
    if med.get("dose") is not None and str(med["dose"]).rstrip("0").rstrip(".") not in [n.rstrip("0").rstrip(".") for n in ocr_nums]:
        m["dose"] = med["dose"]                         # keep the true dose: grounding must notice the mismatch
    return m


def run(formats=("pdf", "scan")):
    out = {}
    for fmt in formats:
        rows = []
        for case in sorted(KEY):
            folder = DATA / fmt / case
            if not folder.exists():
                continue
            t0 = time.time()
            docs, raw = {}, {}
            for d in ("discharge_summary", "prescription"):
                f = next(p for p in folder.iterdir() if p.stem == d)
                doc = to_text(f)
                docs[d] = {k: doc[k] for k in ("text", "method", "low_confidence_numbers", "file")}
                lines = [l for l in doc["text"].splitlines() if l.strip()]
                raw[d] = [m for m in (realign(x, lines) for x in MOCKS[case][d]) if m]
            rows.append(score_case(case, run_checks(case, docs, raw), round(time.time() - t0, 2)))
        s = summarize(rows, f"C. OCR + checks ({fmt}, verified extraction re-pointed to OCR lines)")
        save(f"suite_c_ocr_plus_checks_{fmt}", s, rows)
        out[fmt] = (s, rows)
    return out


if __name__ == "__main__":
    for fmt, (s, rows) in run(tuple(sys.argv[1:]) or ("pdf", "scan")).items():
        print(fmt, {k: v for k, v in s.items() if k in ("errors_caught", "errors_planted", "false_alarms", "specificity", "review_rate", "case_accuracy")})
        for r in rows:
            if not r["correct"]:
                print("   ", r["case"], r["status"], "missed", r["missed"], "FA", r["false_alarms"], (r["review_reason"] or "")[:120])
