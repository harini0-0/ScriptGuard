# ScriptGuard v2 (Person 2's engine + queue + MongoDB)

Unzip to ~/Downloads/sg2:
    scriptguard2/   -> copy INTO the sandbox (engine + agent tools + SKILL.md). No patient data.
    sg2_host/       -> stays on the HOST (dashboard, MongoDB store, intake/OCR, backup runner, demo docs)

## 1. Install (host)
    sudo apt install -y tesseract-ocr poppler-utils
    /usr/bin/python3 -m pip install --user streamlit pytesseract pdfplumber pillow pymongo --break-system-packages

## 2. MongoDB (host only, bound to 127.0.0.1)
    docker start scriptguard-mongo 2>/dev/null || docker run -d --name scriptguard-mongo -p 127.0.0.1:27017:27017 -v ~/mongo-data:/data/db mongo:7

## 3. Put the sandbox part into the sandbox
    mkdir -p ~/sbx && nemoclaw dischargeiq share mount /sandbox ~/sbx     # skip if already mounted
    cp -r ~/Downloads/sg2/scriptguard2 ~/sbx/
    nemoclaw dischargeiq skill install ~/sbx/scriptguard2
    nemoclaw dischargeiq connect      ->  python3 /sandbox/scriptguard2/tools/sg_read.py   ->  exit

## 4. Dashboard (host)
    cd ~/Downloads/sg2
    SG2_SANDBOX=~/sbx/scriptguard2 /usr/bin/python3 -m streamlit run sg2_host/queue_dashboard.py
    Intake      http://localhost:8501/?view=intake
    Board       http://localhost:8501/?view=board
    Pharmacist  http://localhost:8501/?view=pharmacist

## 5. One token
    Intake: upload 2 files (or "Queue a demo case") -> token
    Pharmacist: Call next token -> copy prompt -> OpenClaw chat (/new first) -> Refresh
    Verdict -> decision -> every copy of the patient's data is deleted

## Model name
    Backup button and eval use SCRIPTGUARD_LLM_MODEL (default nemotron-light:latest) at
    SCRIPTGUARD_LLM_URL (default http://127.0.0.1:11434/v1).
