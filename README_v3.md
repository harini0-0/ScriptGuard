# ScriptGuard v3: real-world reports + live HTML dashboard

## Folders (unzip into ~/Desktop/dellers)
  scriptguard2/  -> copy INTO the sandbox (engine, real-world layer, agent tools, SKILL.md). No patient data.
  sg2_host/      -> stays on the HOST (server, dashboard pages, MongoDB store, OCR, backup runner, demo docs)

## Start
  cp -r ~/Desktop/dellers/scriptguard2 ~/sbx/
  nemoclaw dischargeiq skill install ~/sbx/scriptguard2
  cd ~/Desktop/dellers
  SG2_SANDBOX=~/sbx/scriptguard2 /usr/bin/python3 sg2_host/server.py

  Pharmacist dashboard  http://localhost:8600/
  Intake                http://localhost:8600/intake
  Waiting-room board    http://localhost:8600/board
