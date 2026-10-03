#!/usr/bin/env python3
"""Agent tool: print the staged documents for ONE case.
Usage: python3 /sandbox/scriptguard2/tools/sg_read.py <case_id>"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "cases"

if len(sys.argv) < 2:
    staged = sorted(p.name for p in CASES.iterdir()) if CASES.exists() else []
    print("Staged cases:", ", ".join(staged) or "(none)")
    sys.exit(0)

case_id = sys.argv[1]
f = CASES / case_id / "ingest.json"
if not f.exists():
    print(f"ERROR: case '{case_id}' is not staged. Only the case called by the pharmacist is available.")
    sys.exit(1)
data = json.loads(f.read_text())
for doc_type in ("discharge_summary", "prescription"):
    d = data["documents"][doc_type]
    print(f"===== {doc_type.upper()} (read via {d['method']}) =====")
    print(d["text"].strip())
    print()
print("Next: extract medications from BOTH documents, copying source_text exactly, then run sg_check.py.")
