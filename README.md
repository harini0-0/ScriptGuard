# ScriptGuard

A private AI safety net for discharge medication mismatches. Built at the Dell x NVIDIA AI Hackathon, Boston (Oct 2026).

ScriptGuard reads a patient's discharge summary and prescription (PDF, scan, photo, or pasted text), finds
medication mismatches, holds the order, and shows the pharmacist exactly which lines conflict. Everything runs
locally on a Dell Pro Max with GB10. Patient data never leaves the machine.

## How it works
1. Intake (host): documents are read (PDF text layer or Tesseract OCR) and stored in MongoDB under a token.
2. Call token (host -> sandbox): only that patient's text, with identifiers redacted, is staged into the
   NVIDIA OpenShell sandbox (no internet, no database access).
3. Extract (sandbox): the OpenClaw agent (via NemoClaw) and a local Nemotron model extract each medicine
   with its exact source line.
4. Check (Python, no AI): grounding against the source, dose / stop / missing / frequency / brand checks.
5. Review: the pharmacist sees the flags side by side and decides. All patient data is then deleted;
   a content-free audit line is kept.

The AI reads. Python decides. The pharmacist approves.

## Stack
NemoClaw + OpenClaw + OpenShell, Ollama (Nemotron), Python, Tesseract OCR, MongoDB, standard-library web server.

## Run
    cp -r scriptguard2 ~/sbx/                      # sandbox mount (nemoclaw <name> share mount /sandbox ~/sbx)
    nemoclaw <name> skill install ~/sbx/scriptguard2
    docker run -d --name scriptguard-mongo -p 127.0.0.1:27017:27017 mongo:7
    SG2_SANDBOX=~/sbx/scriptguard2 python3 sg2_host/server.py
    # dashboard http://localhost:8600/   intake /intake   board /board

## Layout
    scriptguard2/   engine, real-world layer, agent tools, SKILL.md (copied into the sandbox; no patient data)
    sg2_host/       server, dashboard pages, intake/OCR, MongoDB store, backup runner, demo documents

All demo data is synthetic (fictional hospitals and patients). Prototype, not a clinical tool.
