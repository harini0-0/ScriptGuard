"""Suite A: checking logic alone. Typed text + hand-verified extractions (no OCR, no model)."""
import json
import time
from metrics import DATA, KEY, run_checks, score_case, summarize, save

MOCKS = json.loads((DATA / "mocks.json").read_text())


def run():
    rows = []
    for case in sorted(KEY):
        docs = {}
        for d in ("discharge_summary", "prescription"):
            text = (DATA / "text" / case / f"{d}.txt").read_text()
            docs[d] = {"text": text, "method": "text", "low_confidence_numbers": [], "file": f"{d}.txt"}
        raw = {d: MOCKS[case][d] for d in docs}
        t0 = time.time()
        rows.append(score_case(case, run_checks(case, docs, raw), round(time.time() - t0, 4)))
    s = summarize(rows, "A. Checks only (verified extraction, typed text)")
    save("suite_a_checks_only", s, rows)
    return s, rows


if __name__ == "__main__":
    s, _ = run()
    print(json.dumps({k: v for k, v in s.items() if k != "per_type"}, indent=1))
