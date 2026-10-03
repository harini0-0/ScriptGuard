# ScriptGuard verification report

Generated 2026-10-03 16:42. All documents are synthetic (fictional hospitals and patients).
The product code is read, never modified. High flags hold an order; low flags are advisory and not scored.

## Headline metrics

| Suite | Cases | Errors caught | Precision | F1 | Specificity | False alarms | Sent to review | Case accuracy | Time/case |
|---|---|---|---|---|---|---|---|---|---|
| A. Checks only (verified extraction, typed text) | 19 | 15/15 (100.0%) | 93.8% | 0.968 | 100.0% | 1 | 0.0% | 94.7% | 0.00 s |
| C. OCR + checks (pdf, verified extraction re-pointed to OCR lines) | 17 | 13/13 (100.0%) | 92.9% | 0.963 | 100.0% | 1 | 0.0% | 94.1% | 0.01 s |
| C. OCR + checks (scan, verified extraction re-pointed to OCR lines) | 19 | 15/15 (100.0%) | 93.8% | 0.968 | 85.7% | 1 | 5.3% | 89.5% | 4.76 s |

_Suite E (local Nemotron, end to end) not run yet: `python3 run_all.py --with-model text` on the GB10._

## B. Reading fidelity (medication lines)

| Format | Medication lines | Exact line | Found (≥0.92 similar, numbers exact) | Dose numbers exact | Approx. char error rate | Time/document |
|---|---|---|---|---|---|---|
| pdf (pdf_text_layer) | 86 | 100.0% | 100.0% | 100.0% | 0.0% | 0.00 s |
| scan (ocr_image, ocr_scanned_pdf) | 105 | 97.1% | 99.0% | 99.0% | 0.1% | 2.35 s |

  Numeric OCR error (scan, case_003, discharge_summary): `Metformin 500 mg by mouth twice daily` read as `- Metformin S00 mg by mouth twice daily`

## D. Identifier redaction before the sandbox

- Identifier instances checked: 44 (name, UHID, DOB, address, PIN, phone, email)
- Leak rate with the name and MRN typed at intake: **0.0%**
- Leak rate with pattern rules only: 0.0%
- Medication lines kept after redaction: **100.0%** of 105

## Per-suite detail

### A. Checks only (verified extraction, typed text)

| Error type | Planted | Caught | Recall |
|---|---|---|---|
| dose_mismatch | 6 | 6 | 100.0% |
| frequency_mismatch | 2 | 2 | 100.0% |
| missing_from_orders | 4 | 4 | 100.0% |
| stopped_but_ordered | 3 | 3 | 100.0% |

Status confusion (expected -> actual): CLEAN -> CLEAN: 7, HELD -> HELD: 12
Advisory low flags raised: 2. Excluded from scoring: case_005.

| Case | Scenario | Expected | Actual | Missed | False alarms | Note |
|---|---|---|---|---|---|---|
| case_011 | salt_form | HELD | HELD | - | not_in_summary metoprolol tartrate |  |

### C. OCR + checks (pdf, verified extraction re-pointed to OCR lines)

| Error type | Planted | Caught | Recall |
|---|---|---|---|
| dose_mismatch | 6 | 6 | 100.0% |
| frequency_mismatch | 1 | 1 | 100.0% |
| missing_from_orders | 3 | 3 | 100.0% |
| stopped_but_ordered | 3 | 3 | 100.0% |

Status confusion (expected -> actual): CLEAN -> CLEAN: 6, HELD -> HELD: 11
Advisory low flags raised: 1. Excluded from scoring: case_005.

| Case | Scenario | Expected | Actual | Missed | False alarms | Note |
|---|---|---|---|---|---|---|
| case_011 | salt_form | HELD | HELD | - | not_in_summary metoprolol tartrate |  |

### C. OCR + checks (scan, verified extraction re-pointed to OCR lines)

| Error type | Planted | Caught | Recall |
|---|---|---|---|
| dose_mismatch | 6 | 6 | 100.0% |
| frequency_mismatch | 2 | 2 | 100.0% |
| missing_from_orders | 4 | 4 | 100.0% |
| stopped_but_ordered | 3 | 3 | 100.0% |

Status confusion (expected -> actual): CLEAN -> CLEAN: 6, CLEAN -> NEEDS_REVIEW: 1, HELD -> HELD: 12
Advisory low flags raised: 2. Excluded from scoring: case_005.

| Case | Scenario | Expected | Actual | Missed | False alarms | Note |
|---|---|---|---|---|---|---|
| case_003 | clean | CLEAN | NEEDS_REVIEW | - | - | Some values could not be matched to the document. Check the originals by hand: metformin: discharge summary: d |
| case_011 | salt_form | HELD | HELD | - | not_in_summary metoprolol tartrate |  |

## How to read these results

- **A** isolates the checking logic: hand-verified extractions on typed text.
- **B** isolates reading: how faithfully PDFs and scans become text, measured on medication lines only.
- **C** shows whether reading noise changes the verdict: verified extractions re-pointed to the lines the reader produced.
- **D** checks that identifiers are removed before the chart enters the sandbox without removing medicines.
- **E** is the honest end-to-end number: reading + local Nemotron extraction + checks.

## Known limitations

- Small synthetic test set (20 cases); results show behaviour, not clinical accuracy. Validate on de-identified real data before any deployment.
- case_005 (a home medication silently dropped) is out of scope: it needs the home medication list as a third document.
- case_011: a salt-form change (metoprolol succinate in the summary, tartrate on the prescription) raises the planted 'missing' flag and also a 'not in summary' flag for tartrate. Scored strictly as one false alarm; it is the same error seen from both sides.
- case_003 (scan): OCR read '500 mg' as 'S00 mg'. Grounding could not verify the dose, so the case went to 'check by hand' instead of a wrong verdict. Scored as not correct (it lowers specificity), but it is the intended safe behaviour.
- Suite C assumes a perfect extractor working on the reader's output; suite E measures the real model.
- Model output can vary between runs; rerun suite E to see run-to-run spread.
- Brand-name coverage is a curated list (about 50 brands); unknown brands fall back to the printed name.
