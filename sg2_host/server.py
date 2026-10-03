"""ScriptGuard host server: serves the pharmacist dashboard (original HTML design), intake, and board.
Host only, bound to 127.0.0.1. Standard library HTTP server.

Run:  SG2_SANDBOX=~/sbx/scriptguard2 /usr/bin/python3 sg2_host/server.py
Open: http://localhost:8600/          pharmacist dashboard (queue + end-of-day audit)
      http://localhost:8600/intake    discharge desk
      http://localhost:8600/board     waiting-room board
"""
import datetime
import json
import os
import shlex
import subprocess
import time
import shutil
import sys
import threading
import traceback
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config   # noqa: E402
import intake   # noqa: E402
import store    # noqa: E402
import realworld  # noqa: E402

WEB = config.HOST_DIR / "web"
LOCK = threading.Lock()
AUTO = os.environ.get("SG_AUTO", "1") != "0"            # auto-call and auto-check
AGENT_CMD = os.environ.get("SG_AGENT_CMD", "")          # optional: non-interactive OpenClaw command, {prompt} placeholder
AGENT_WAIT = int(os.environ.get("SG_AGENT_WAIT", "240"))
PROGRESS = {}                                           # token -> {"stage": str, "error": str}
METHOD_LABEL = {"text": "Typed text", "pdf_text_layer": "Digital PDF",
                "ocr_scanned_pdf": "Scanned PDF, read with OCR", "ocr_image": "Photo or scan, read with OCR"}
DOC_LABEL = {"discharge_summary": "Discharge summary", "prescription": "Prescription"}
DEMO_LABELS = {
    "realistic_held": "Realistic scan: ortho discharge, table + brands (3 planted errors)",
    "realistic_clean": "Realistic scan: ortho discharge, table + brands (clean)",
    "case_002": "Warfarin stopped but still prescribed", "case_003": "Clean discharge",
    "case_004": "Gabapentin 300 mg vs 3000 mg",
}
DEMO_PATIENT = {"realistic_held": ("Anjali Rao", "1800012345"), "realistic_clean": ("Anjali Rao", "1800012345")}


# ------------------------------------------------------------------ state helpers
def now_hm():
    return datetime.datetime.now().strftime("%H:%M")


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)          # readers never see a half-written file


def load_queue():
    for _ in range(5):
        try:
            return json.loads(config.QUEUE_FILE.read_text()) if config.QUEUE_FILE.exists() else []
        except json.JSONDecodeError:
            time.sleep(0.05)
    return []


def save_queue(q):
    write_atomic(config.QUEUE_FILE, json.dumps(q, indent=2))


def result_for(case_id):
    f = config.SANDBOX_RESULTS / f"{case_id}.json"
    try:
        return json.loads(f.read_text()) if f.exists() else None
    except json.JSONDecodeError:
        return None                # still being written; next refresh picks it up


def clear_dir(path):
    if path.exists():
        for p in path.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()


def sandbox_contents():
    return sorted(p.name for p in config.SANDBOX_CASES.iterdir()) if config.SANDBOX_CASES.exists() else []


def mask(mrn):
    m = str(mrn or "")
    return ("••" + m[-2:]) if len(m) >= 2 else "••"


def sources(rec):
    out = []
    for k in ("discharge_summary", "prescription"):
        d = rec["documents"][k]
        how = METHOD_LABEL.get(d["method"], d["method"])
        low = len(d.get("low_confidence_numbers") or [])
        if low:
            how += f" ({low} uncertain number{'s' if low > 1 else ''})"
        out.append({"doc": DOC_LABEL[k], "how": how})
    return out


def agent_prompt(case_id):
    t, w = config.TOOLS_IN_SANDBOX, config.WORK_IN_SANDBOX
    return (f"Use the scriptguard skill to check {case_id} only.\n"
            f"Step 1: run python3 {t}/sg_read.py {case_id}\n"
            f"Step 2: extract every medication from both documents as JSON in the format from the scriptguard "
            f"SKILL.md (tables: one medication per row, source_text = the whole row exactly as printed) "
            f"and save it to {w}/{case_id}.json\n"
            f"Step 3: run python3 {t}/sg_check.py {case_id} @{w}/{case_id}.json\n"
            f"Step 4: reply with exactly what sg_check.py printed.")


def read_audit():
    if not config.AUDIT_FILE.exists():
        return []
    today = datetime.date.today().isoformat()
    out = []
    for line in config.AUDIT_FILE.read_text().splitlines():
        try:
            a = json.loads(line)
        except json.JSONDecodeError:
            continue
        if a.get("date") == today and "id" in a:
            out.append(a)
    return out


def build_state():
    q = load_queue()
    cases = []
    for t in q:
        if t["status"] == "DONE":
            continue
        rec = store.get(t["token"])
        if rec is None:
            continue
        r = result_for(t["case_id"]) if t["status"] == "CALLED" else None
        if t["status"] == "WAITING":
            status = "pending"
        elif r is None:
            status = "processing"
        else:
            status = "review" if r["status"] == "NEEDS_REVIEW" else "ready"
        c = {"id": t["token"], "name": rec.get("name") or "Unnamed", "mrn": rec.get("mrn") or "",
             "status": status, "uploaded": t.get("uploaded") or t.get("created", ""), "sources": sources(rec),
             "checked": (r or {}).get("checked", 0), "flags": (r or {}).get("flags", [])}
        if status == "processing":
            c["prompt"] = agent_prompt(t["case_id"])
            c["progress"] = PROGRESS.get(t["token"], {"stage": "Starting the check..." if AUTO else ""})
            c["auto"] = AUTO
        if r:
            c["reason"] = r.get("review_reason") or r.get("message")
            c["evidence"] = r.get("evidence")
        cases.append(c)
    closed = read_audit()
    for a in closed:
        cases.append(dict(a, status="closed"))
    return {"cases": cases, "closed": closed, "sandbox": sandbox_contents(), "store": store.backend()}


# ------------------------------------------------------------------ actions
def new_token(name, mrn, label, documents):
    with LOCK:
        q = load_queue()
        n = len(q) + 1
        token, case_id = f"T-{n:03d}", f"tkn_{n:03d}"
        where = store.save(token, {"case_id": case_id, "label": label, "name": name, "mrn": mrn,
                                   "created_at": store.now_iso(), "status": "WAITING", "documents": documents})
        q.append({"token": token, "case_id": case_id, "status": "WAITING", "uploaded": now_hm()})
        save_queue(q)
    rec = {"documents": documents}
    return {"token": token, "store": "MongoDB" if where == "mongo" else "local files", "sources": sources(rec)}


def call_next():
    with LOCK:
        q = load_queue()
        if any(t["status"] == "CALLED" for t in q):
            raise ValueError("Finish the current patient first: only one chart is in the sandbox at a time.")
        nxt = next((t for t in q if t["status"] == "WAITING"), None)
        if nxt is None:
            raise ValueError("No one is waiting.")
        rec = store.get(nxt["token"])
        docs = {}
        for k, d in rec["documents"].items():
            docs[k] = {"text": realworld.redact(d["text"], rec.get("name"), rec.get("mrn")),
                       "method": d["method"], "low_confidence_numbers": d.get("low_confidence_numbers") or [],
                       "file": "document" + Path(d.get("file") or "").suffix}
        config.SANDBOX_CASES.mkdir(parents=True, exist_ok=True)
        config.SANDBOX_WORK.mkdir(parents=True, exist_ok=True)
        config.SANDBOX_RESULTS.mkdir(parents=True, exist_ok=True)
        clear_dir(config.SANDBOX_CASES)
        dest = config.SANDBOX_CASES / nxt["case_id"]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "ingest.json").write_text(json.dumps({"case_id": nxt["case_id"], "documents": docs}, indent=2))
        nxt["status"] = "CALLED"
        save_queue(q)
        store.update(nxt["token"], status="CALLED")
        return {"token": nxt["token"], "case_id": nxt["case_id"]}


def _process(token, case_id):
    """Automatic check: OpenClaw agent first (if SG_AGENT_CMD is set), else/fallback local model + same checks."""
    result_file = config.SANDBOX_RESULTS / f"{case_id}.json"
    try:
        if AGENT_CMD:
            PROGRESS[token] = {"stage": "The OpenClaw agent is checking the chart in the sandbox..."}
            cmd = AGENT_CMD.replace("{prompt}", shlex.quote(agent_prompt(case_id)))
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.time() + AGENT_WAIT
            while time.time() < deadline and not result_file.exists():
                time.sleep(2)
            if proc.poll() is None and result_file.exists():
                proc.terminate()
        if not result_file.exists():
            PROGRESS[token] = {"stage": "Extracting medicines with the local model and running the checks..."}
            run_backup(token)
        PROGRESS.pop(token, None)
    except Exception as e:
        traceback.print_exc()
        PROGRESS[token] = {"stage": "Automatic check failed", "error": str(e)}


def start_processing(token, case_id):
    threading.Thread(target=_process, args=(token, case_id), daemon=True).start()


def auto_call():
    """Call the next waiting token if the counter is free (one chart in the sandbox at a time)."""
    if not AUTO:
        return
    try:
        r = call_next()
        start_processing(r["token"], r["case_id"])
    except ValueError:
        pass


def run_backup(token):
    import backup_runner
    t = next((x for x in load_queue() if x["token"] == token), None)
    if t is None or t["status"] != "CALLED":
        raise ValueError("This token is not being served.")
    staged = config.SANDBOX_CASES / t["case_id"] / "ingest.json"
    docs = json.loads(staged.read_text())["documents"]      # the same redacted text the agent sees
    r = backup_runner.run(t["case_id"], docs)
    return {"status": r["status"]}


def close_case(token, decision):
    with LOCK:
        q = load_queue()
        t = next((x for x in q if x["token"] == token), None)
        if t is None or t["status"] == "DONE":
            raise ValueError("Unknown or already closed token.")
        rec = store.get(token) or {"documents": {}}
        r = result_for(t["case_id"]) or {}
        with open(config.AUDIT_FILE, "a") as log:       # no document text, no full identifiers
            log.write(json.dumps({
                "id": token, "date": datetime.date.today().isoformat(), "name": "Details deleted",
                "mrn": mask(rec.get("mrn")), "checked": r.get("checked", 0),
                "flags": [{"severity": f["severity"], "type": f["type"], "drug": f["drug"]} for f in r.get("flags", [])],
                "review": r.get("status") == "NEEDS_REVIEW" or not r, "decision": decision, "closed": now_hm(),
                "doc_fingerprints": [d.get("sha256") for d in rec["documents"].values()]}) + "\n")
        removed = store.delete(token)
        shutil.rmtree(config.SANDBOX_CASES / t["case_id"], ignore_errors=True)
        for p in (config.SANDBOX_WORK / f"{t['case_id']}.json", config.SANDBOX_RESULTS / f"{t['case_id']}.json"):
            if p.exists():
                p.unlink()
        clear_dir(config.SANDBOX_CASES)
        t["status"] = "DONE"
        save_queue(q)
        return {"deleted": removed + ["sandbox chart", "agent files"]}


def list_demos():
    out = []
    for fmt in ("scan", "pdf", "text"):
        root = config.DEMO_DIR / fmt
        if root.exists():
            for c in sorted(p.name for p in root.iterdir()):
                out.append({"id": f"{fmt}/{c}", "label": f"{DEMO_LABELS.get(c, c)} [{fmt}]"})
    return out


def queue_demo(demo_id):
    fmt, case = demo_id.split("/", 1)
    root = config.DEMO_DIR / fmt / case
    docs = {}
    for key in ("discharge_summary", "prescription"):
        f = next(p for p in root.iterdir() if p.stem == key)
        docs[key] = intake.from_bytes(f.read_bytes(), f.name)
    name, mrn = DEMO_PATIENT.get(case, (f"Demo patient {case[-3:]}", f"DEMO{case[-3:]}"))
    return new_token(name, mrn, f"demo {demo_id}", docs)


# ------------------------------------------------------------------ HTTP
def page(body_file):
    return ((WEB / "_head.html").read_text() + (WEB / body_file).read_text()).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/dashboard"):
                return self._send(200, page("_dashboard_body.html"), "text/html; charset=utf-8")
            if path == "/intake":
                return self._send(200, page("_intake_body.html"), "text/html; charset=utf-8")
            if path == "/board":
                return self._send(200, page("_board_body.html"), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._send(200, build_state())
            if path == "/api/demos":
                return self._send(200, {"demos": list_demos()})
            return self._send(404, {"error": "not found"})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            if path == "/api/intake":
                ctype = self.headers.get("Content-Type", "")
                msg = BytesParser(policy=policy.default).parsebytes(
                    b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
                fields, files = {}, {}
                for part in msg.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    if part.get_filename():
                        files[name] = (part.get_filename(), part.get_payload(decode=True) or b"")
                    else:
                        fields[name] = (part.get_payload(decode=True) or b"").decode("utf-8", "replace").replace("\r\n", "\n").strip()
                docs = {}
                for key in ("discharge_summary", "prescription"):
                    pasted = fields.get(f"{key}_text", "")
                    if key in files and files[key][1]:
                        docs[key] = intake.from_bytes(files[key][1], files[key][0])
                    elif pasted:
                        docs[key] = intake.from_text(pasted, key)
                    else:
                        raise ValueError(f"Add the {DOC_LABEL[key].lower()}: upload a file or paste its text.")
                    if not docs[key]["text"].strip():
                        raise ValueError(f"No text could be read from the {DOC_LABEL[key].lower()}. "
                                         "Upload a clearer, straight image or the PDF.")
                out = new_token(fields.get("name", ""), fields.get("mrn", ""), "upload", docs); auto_call()
                return self._send(200, out)
            body = json.loads(raw or b"{}")
            if path == "/api/demo":
                out = queue_demo(body["id"]); auto_call()
                return self._send(200, out)
            if path == "/api/call":
                out = call_next()
                if AUTO:
                    start_processing(out["token"], out["case_id"])
                return self._send(200, out)
            if path == "/api/backup":
                return self._send(200, run_backup(body["token"]))
            if path == "/api/close":
                out = close_case(body["token"], body.get("decision", "").strip()); auto_call()
                return self._send(200, out)
            return self._send(404, {"error": "not found"})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})


if __name__ == "__main__":
    port = 8600
    print(f"ScriptGuard on http://localhost:{port}/  (intake: /intake, board: /board)")
    print(f"Sandbox folder: {config.SANDBOX_ROOT}   Patient store: {store.backend()}")
    print(f"Automatic checking: {'on' if AUTO else 'off'}   Agent command: {AGENT_CMD or '(not set: local model + same checks)'}")
    for t in load_queue():
        if t["status"] == "CALLED" and not result_for(t["case_id"]):
            start_processing(t["token"], t["case_id"])
    auto_call()
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
