"""Suite E (run on the GB10): real reading -> local Nemotron extraction -> checks. Same prompt as the product.
  export SCRIPTGUARD_LLM_URL=http://127.0.0.1:11434/v1
  export SCRIPTGUARD_LLM_MODEL=nemotron-light:latest
  python3 suite_e_end_to_end.py text            # or: pdf scan
Run when no live patients are being checked (it uses the same model)."""
import json
import os
import re
import sys
import time

os.environ.setdefault("SCRIPTGUARD_LLM_URL", "http://127.0.0.1:11434/v1")
os.environ.setdefault("SCRIPTGUARD_LLM_MODEL", "nemotron-light:latest")
from metrics import DATA, KEY, realworld, run_checks, score_case, summarize, save  # noqa: E402

realworld.patch_ocr_rotation()
from scriptguard import extract as p2extract        # noqa: E402
from scriptguard.ingest import to_text               # noqa: E402

p2extract.SYSTEM_PROMPT = p2extract.SYSTEM_PROMPT + realworld.EXTRA_RULES


def raw_meds(text, doc_type):
    for _ in range(2):
        try:
            raw = re.sub(r"```(?:json)?", "", p2extract._call_llm(text, doc_type)).strip()
            m = re.search(r"\{.*\}", raw, re.S)
            obj = json.loads(m.group(0) if m else raw)
            meds = obj.get("medications", obj if isinstance(obj, list) else [])
            return [x for x in meds if isinstance(x, dict)]
        except (json.JSONDecodeError, KeyError, AttributeError):
            continue
    raise RuntimeError("model did not return valid JSON twice")


def run(formats=("text",)):
    out = {}
    for fmt in formats:
        rows = []
        for case in sorted(KEY):
            folder = DATA / fmt / case
            if not folder.exists():
                continue
            t0 = time.time()
            try:
                docs, raw = {}, {}
                for d in ("discharge_summary", "prescription"):
                    f = next(p for p in folder.iterdir() if p.stem == d)
                    doc = to_text(f)
                    doc["text"] = realworld.redact(doc["text"])   # the product stages redacted text
                    docs[d] = {k: doc[k] for k in ("text", "method", "low_confidence_numbers", "file")}
                    raw[d] = raw_meds(docs[d]["text"], d)
                row = score_case(case, run_checks(case, docs, raw), round(time.time() - t0, 1))
            except Exception as e:
                row = {"case": case, "error": str(e), "seconds": round(time.time() - t0, 1)}
            rows.append(row)
            print(f"  {fmt} {case}: {row.get('status', 'ERROR')} {'OK' if row.get('correct') else 'MISS'} ({row['seconds']} s)", flush=True)
        s = summarize(rows, f"E. End to end ({fmt}): reading + local {os.environ['SCRIPTGUARD_LLM_MODEL']} + checks")
        save(f"suite_e_end_to_end_{fmt}", s, rows)
        out[fmt] = s
    return out


if __name__ == "__main__":
    for fmt, s in run(tuple(sys.argv[1:]) or ("text",)).items():
        print(fmt, {k: v for k, v in s.items() if k in ("errors_caught", "errors_planted", "false_alarms",
                                                        "specificity", "review_rate", "case_accuracy", "seconds_per_case")})
