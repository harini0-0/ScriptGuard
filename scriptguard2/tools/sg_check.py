#!/usr/bin/env python3
"""Agent tool: grounding + comparison with Person 2's engine. Python decides, not the model.
Usage: python3 /sandbox/scriptguard2/tools/sg_check.py <case_id> @/sandbox/scriptguard2/work/<case_id>.json
Extraction JSON:
 {"discharge_summary": {"medications": [...]}, "prescription": {"medications": [...]}}
 each medication: {"drug","dose","unit","frequency","status","source_text"}"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import realworld  # noqa: E402,F401  (patches names, schedules, unit-less doses)
from scriptguard.pipeline import check_extraction  # noqa: E402

ALIASES = {"discharge_summary": ("discharge_summary", "summary", "summary_meds"),
           "prescription": ("prescription", "orders", "rx", "rx_meds")}


def load_arg(v):
    if v.startswith("@"):
        return json.loads(Path(v[1:]).read_text())
    return json.loads(v)


def meds_for(data, doc_type):
    for key in ALIASES[doc_type]:
        if key in data:
            val = data[key]
            return val.get("medications", []) if isinstance(val, dict) else val
    return []


if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)
case_id = sys.argv[1]
staged = ROOT / "cases" / case_id / "ingest.json"
if not staged.exists():
    print(f"ERROR: case '{case_id}' is not staged.")
    sys.exit(1)
try:
    extracted = load_arg(sys.argv[2])
except Exception as e:
    print(f"ERROR: extraction is not valid JSON ({e}). Fix the JSON and run again.")
    sys.exit(1)

ingest = json.loads(staged.read_text())
extraction = {"case_id": case_id, "documents": {}}
for doc_type in ("discharge_summary", "prescription"):
    doc = dict(ingest["documents"][doc_type])
    doc["medications"] = meds_for(extracted, doc_type)
    extraction["documents"][doc_type] = doc

evidence = json.loads((ROOT / "engine" / "evidence.json").read_text())
result = check_extraction(extraction, evidence_db=evidence)
raw = {k: meds_for(extracted, k) for k in ("discharge_summary", "prescription")}
result = realworld.build_flags(result, raw, extraction["documents"])
result["source"] = "agent"
out_dir = ROOT / "results"
out_dir.mkdir(parents=True, exist_ok=True)
tmp = out_dir / f"{case_id}.json.tmp"
tmp.write_text(json.dumps(result, indent=2))
os.replace(tmp, out_dir / f"{case_id}.json")

print(f"CASE {case_id}: {result['status']}  ({result['message']})")
print(f"Medicines checked: {result['checked']}")
for f in result["flags"]:
    print(f"- {f['severity']} {f['type']} ({f['drug']}): {f['explanation']}")
if result.get("review_reason"):
    print(f"- REVIEW: {result['review_reason']}")
if result.get("evidence"):
    print(f"- Evidence: {result['evidence']}")
print("Report exactly this to the pharmacist. The order stays on hold until a pharmacist decides."
      if result["status"] != "CLEAN" else "No discrepancies found by the checks run.")
