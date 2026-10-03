"""Paths shared by the host-side code."""
import os
import sys
from pathlib import Path

HOST_DIR = Path(__file__).resolve().parent
ENGINE_DIR = HOST_DIR.parent / "scriptguard2" / "engine"       # host copy of Person 2's engine
sys.path.insert(0, str(ENGINE_DIR))

# The sandbox copy of scriptguard2, seen from the host through `nemoclaw ... share mount`
SANDBOX_ROOT = Path(os.path.expanduser(os.environ.get("SG2_SANDBOX", "~/sbx/scriptguard2")))
SANDBOX_CASES = SANDBOX_ROOT / "cases"
SANDBOX_WORK = SANDBOX_ROOT / "work"
SANDBOX_RESULTS = SANDBOX_ROOT / "results"

DATA_DIR = HOST_DIR / "data"            # host-only: queue, local fallback store, minimal audit
DATA_DIR.mkdir(exist_ok=True)
QUEUE_FILE = DATA_DIR / "queue.json"
AUDIT_FILE = DATA_DIR / "audit_minimal.jsonl"
LOCAL_STORE = DATA_DIR / "patients"     # used only when MongoDB is not reachable
DEMO_DIR = HOST_DIR / "demo_docs"

TOOLS_IN_SANDBOX = "/sandbox/scriptguard2/tools"
WORK_IN_SANDBOX = "/sandbox/scriptguard2/work"

OLLAMA_V1 = os.environ.get("SCRIPTGUARD_LLM_URL", "http://127.0.0.1:11434/v1")
MODEL = os.environ.get("SCRIPTGUARD_LLM_MODEL", "nemotron-light:latest")
