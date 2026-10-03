# ScriptGuard verification (separate from the product)

Measures ScriptGuard on 20 labeled synthetic cases. It READS the product code in ../scriptguard2 and never
modifies it, so the numbers describe exactly what runs in the demo. Results: reports/VERIFICATION_REPORT.md

## Layout
    verification/
      data/text, data/pdf, data/scan   18 cases from Person 2 + 2 realistic Indian-format cases (scan and text)
      data/answer_key.json             planted errors per case (15 scored), clean cases, notes
      data/mocks.json                  hand-verified extractions (ground truth for suites A and C)
      metrics.py                       metric definitions and scoring (shared)
      suite_a_checks_only.py           checking logic alone
      suite_b_ocr_fidelity.py          reading fidelity on medication lines
      suite_c_ocr_plus_checks.py       does reading noise change the verdict
      suite_d_redaction.py             identifiers removed, medicines kept
      suite_e_end_to_end.py            reading + local Nemotron + checks (GB10)
      run_all.py                       runs suites, writes the report
      reports/                         JSON per suite + VERIFICATION_REPORT.md

## Run (from ~/Desktop/dellers/verification, next to scriptguard2/ and sg2_host/)
    /usr/bin/python3 run_all.py --report-only          # rebuild the report from the included results
    /usr/bin/python3 run_all.py                         # rerun suites A-D on this machine (~5 min, no model)
    export SCRIPTGUARD_LLM_MODEL=nemotron-light:latest
    /usr/bin/python3 run_all.py --with-model text       # add suite E with the local model (text)
    /usr/bin/python3 run_all.py --with-model text scan  # add scans too (slower)
Run suite E only when no live patients are being checked (it uses the same model).
If the product is elsewhere: export SCRIPTGUARD_PRODUCT=/path/to/folder/containing/scriptguard2

## Metrics
error recall, precision, F1, specificity on clean cases, false alarms (total and per case), review rate,
case accuracy, recall per error type, status confusion matrix, time per case; reading fidelity (exact line,
found with exact numbers, dose numbers exact, character error rate, time per document); redaction leak rate
and medication lines kept. Definitions are at the top of metrics.py.
