# ScriptGuard

A private AI safety net for discharge medication mismatches. Built at the Dell x NVIDIA AI Hackathon, Boston (Oct 2026).

ScriptGuard reads a patient's discharge summary and prescription (PDF, scan, photo, or pasted text), finds
medication mismatches, holds the order, and shows the pharmacist exactly which lines conflict. Everything runs
locally on a Dell Pro Max with GB10. Patient data never leaves the machine.

The AI reads. Python decides. The pharmacist approves.

## How it works
1. Intake (host): documents are read (PDF text layer or Tesseract OCR) and stored in MongoDB under a token.
2. The token is called automatically: only that patient's text, with identifiers redacted, enters the
   NVIDIA OpenShell sandbox (no internet, no database access).
3. A local Nemotron model extracts each medicine with its exact source line (OpenClaw agent via NemoClaw).
4. Python checks, no AI: grounding against the source, dose / stopped / missing / frequency / brand checks.
5. The pharmacist sees the flags side by side and decides. All patient data is then deleted;
   a content-free audit line is kept.

## Verification (synthetic data)
| What we tested | Result |
|---|---|
| Checking logic, 15 planted errors across 19 cases | 15/15 caught, 100% specificity |
| Reading scans (105 medication lines) | 97% exact, 99% with every dose number correct |
| Identifiers before the sandbox | 0% leaked, 100% of medicines kept |

Full methodology, metrics, and limitations: [verification/reports/VERIFICATION_REPORT.md](verification/reports/VERIFICATION_REPORT.md)

## Stack
NemoClaw + OpenClaw + OpenShell, Ollama (Nemotron), Python, Tesseract OCR, MongoDB.

## Run
    nemoclaw <name> share mount /sandbox ~/sbx
    cp -r scriptguard2 ~/sbx/ && nemoclaw <name> skill install ~/sbx/scriptguard2
    docker run -d --name scriptguard-mongo -p 127.0.0.1:27017:27017 mongo:7
    SG2_SANDBOX=~/sbx/scriptguard2 python3 sg2_host/server.py
    # dashboard http://localhost:8600/   intake /intake   board /board

## Layout
    scriptguard2/   engine, real-world layer, agent tools, SKILL.md (copied into the sandbox; no patient data)
    sg2_host/       server, dashboard pages, intake/OCR, MongoDB store, demo documents
    verification/   test suites, synthetic test data, answer key, reports

All data is synthetic (fictional hospitals and patients). Prototype, not a clinical tool.
