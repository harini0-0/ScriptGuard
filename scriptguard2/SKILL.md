---
name: scriptguard
description: Checks one patient's discharge summary against the discharge prescription and flags medication mismatches for the pharmacist. Use when asked to check, process, or review a case or token (for example "check tkn_001").
---

# ScriptGuard: discharge medication check

## HARD RULES
- Work on ONLY the single case_id the user names. Never list or open other cases.
- You extract. Python decides. Never compare doses or judge safety yourself.
- Your final answer must repeat ONLY what sg_check.py printed.

## Workflow
1. Read the case:
   `python3 /sandbox/scriptguard2/tools/sg_read.py <case_id>`

2. Extract every medication from BOTH documents into this exact JSON:
   ```json
   {"discharge_summary": {"medications": [
      {"drug": "gabapentin", "dose": 300, "unit": "mg", "frequency": "three times daily",
       "status": "continue", "source_text": "- Gabapentin 300 mg by mouth three times daily"}]},
    "prescription": {"medications": [
      {"drug": "gabapentin", "dose": 3000, "unit": "mg", "frequency": "three times daily",
       "status": "continue", "source_text": "- Gabapentin 3000 mg capsule by mouth three times daily"}]}}
   ```
   Rules:
   1. Extract every medication that is explicitly listed. Do not add medications that are not written.
   2. "source_text" must be copied character-for-character from the document: the exact line the
      medication appears in. Do not paraphrase, fix typos, or reformat it.
   3. "dose" is the number exactly as written (3000 stays 3000, even if it looks wrong). null if none.
   4. "unit" as written (mg, mcg, g, units, mL). null if missing.
   5. "status": "stop" if the document says stop, discontinue, or hold; "new" if newly started;
      otherwise "continue". Prescription items are "continue".
   6. For the discharge summary, use the discharge medication section and any line telling the
      patient to stop or change a medication.
   7. If unsure, still copy what is written. Never guess or calculate.
   8. Tables (MEDICINE | DOSAGE | FREQUENCY | SCHEDULE | DURATION): one medication per table row.
      source_text is the whole row exactly as printed, e.g. "TAB AUGMENTIN 625MG 1TAB 1-0-1 3DAYS".
      drug is the name as printed without TAB/CAP (e.g. "AUGMENTIN", "PAN D"); keep brand names.
      frequency is the schedule as printed (e.g. "1-0-1", "BD", "TDS"). If the DOSAGE cell is empty, dose is null.
   9. Ignore headers, addresses, vitals, lab values, phone numbers, and footers. Lines marked [REDACTED] are not medicines.
   10. If OCR garbled a name (e.g. "P AND ¢"), copy it exactly as printed; never fix it.

3. Save the JSON to `/sandbox/scriptguard2/work/<case_id>.json` and run:
   `python3 /sandbox/scriptguard2/tools/sg_check.py <case_id> @/sandbox/scriptguard2/work/<case_id>.json`
   If it reports invalid JSON, fix it and run again.

4. Reply with exactly what sg_check.py printed.

All data is synthetic. Prototype, not a clinical tool.
