"""ScriptGuard v2: token queue on the host, Person 2's engine for checking.
Run:  /usr/bin/python3 -m streamlit run sg2_host/queue_dashboard.py
Screens:
  http://localhost:8501/?view=intake       upload documents, get a token
  http://localhost:8501/?view=board        waiting-room "now serving" (auto-refresh)
  http://localhost:8501/?view=pharmacist   pharmacist review
Env: SG2_SANDBOX (default ~/sbx/scriptguard2), MONGO_URI, SCRIPTGUARD_LLM_MODEL"""
import datetime
import html
import json
import re
import shutil
import time

import streamlit as st

import config
import intake
import store

st.set_page_config(page_title="ScriptGuard", page_icon="💊", layout="wide")
st.markdown("""
<style>
:root { --chart:#1F5E7A; --hold:#B3261E; --pass:#2E6B4A; --review:#8A5A00; --ink:#16232B; }
.block-container { padding-top: 1.4rem; max-width: 1400px; }
h1 { color: var(--chart); margin-bottom: 0; }
.serving { font-size: 4.5rem; font-weight: 700; color: var(--chart); line-height: 1; }
.token { font-size: 1.6rem; font-weight: 600; color: var(--chart); }
.stamp { display:inline-block; border:4px solid currentColor; border-radius:6px;
         padding:0.3rem 1rem; font-size:1.8rem; font-weight:700; transform:rotate(-3deg); margin:0.4rem 0; }
.stamp.HELD { color: var(--hold); } .stamp.CLEAN { color: var(--pass); }
.stamp.NEEDS_REVIEW { color: var(--review); } .stamp.WAIT { color:#5B6B73; }
.doc { background:#FFFFFF; color:var(--ink); border:1px solid #D9E0DE; border-radius:4px;
       padding:0.9rem 1rem; font-family: ui-monospace, Menlo, Consolas, monospace;
       font-size:0.88rem; line-height:1.55; white-space:pre-wrap; }
.doc .bad { background:#FCEAE8; border-left:4px solid var(--hold); display:block;
            margin-left:-0.5rem; padding-left:0.35rem; }
.doc .warn { background:#FBF1DC; border-left:4px solid var(--review); display:block;
             margin-left:-0.5rem; padding-left:0.35rem; }
.finding { border-left:4px solid var(--hold); padding:0.45rem 0.8rem; margin:0.3rem 0;
           background:rgba(179,38,30,0.06); }
.finding.review { border-left-color:var(--review); background:rgba(138,90,0,0.08); }
</style>
""", unsafe_allow_html=True)

STAMP = {"HELD": "ORDER HELD", "CLEAN": "PASSED", "NEEDS_REVIEW": "NEEDS REVIEW"}
TYPE_LABEL = {"dose_mismatch": "Dose mismatch", "stopped_but_ordered": "Stopped but still ordered",
              "missing_from_orders": "Missing from prescription", "grounding_failed": "Could not verify"}
DOC_LABEL = {"discharge_summary": "Discharge summary", "prescription": "Prescription"}


# ---------------------------------------------------------------- helpers
def now():
    return datetime.datetime.now().strftime("%H:%M:%S")


def load_queue():
    return json.loads(config.QUEUE_FILE.read_text()) if config.QUEUE_FILE.exists() else []


def save_queue(q):
    config.QUEUE_FILE.write_text(json.dumps(q, indent=2))


def result_for(case_id):
    f = config.SANDBOX_RESULTS / f"{case_id}.json"
    return json.loads(f.read_text()) if f.exists() else None


def clear_dir(path):
    if path.exists():
        for p in path.iterdir():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()


def sandbox_contents():
    return sorted(p.name for p in config.SANDBOX_CASES.iterdir()) if config.SANDBOX_CASES.exists() else []


def stage(token, case_id):
    """Write ONLY this token's text into the sandbox. No images, no database access."""
    rec = store.get(token)
    if rec is None:
        raise RuntimeError(f"No stored record for {token}")
    config.SANDBOX_CASES.mkdir(parents=True, exist_ok=True)
    config.SANDBOX_WORK.mkdir(parents=True, exist_ok=True)
    clear_dir(config.SANDBOX_CASES)
    docs = {k: {f: d[f] for f in ("text", "method", "low_confidence_numbers", "file")}
            for k, d in rec["documents"].items()}
    dest = config.SANDBOX_CASES / case_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "ingest.json").write_text(json.dumps({"case_id": case_id, "documents": docs}, indent=2))


def purge_patient(token, case_id):
    """After service: delete every copy of the patient's data. Keep only a content-free audit line."""
    removed = store.delete(token)
    for p in (config.SANDBOX_CASES / case_id,):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            removed.append("sandbox chart")
    for p, label in ((config.SANDBOX_WORK / f"{case_id}.json", "agent extraction"),
                     (config.SANDBOX_RESULTS / f"{case_id}.json", "detailed result")):
        if p.exists():
            p.unlink()
            removed.append(label)
    return removed


def agent_prompt(case_id):
    return (f"Use the scriptguard skill to check {case_id} only.\n"
            f"Step 1: run python3 {config.TOOLS_IN_SANDBOX}/sg_read.py {case_id}\n"
            f"Step 2: extract every medication from both documents as JSON in the format from the "
            f"scriptguard SKILL.md, copying each source_text line exactly, and save it to "
            f"{config.WORK_IN_SANDBOX}/{case_id}.json\n"
            f"Step 3: run python3 {config.TOOLS_IN_SANDBOX}/sg_check.py {case_id} "
            f"@{config.WORK_IN_SANDBOX}/{case_id}.json\n"
            f"Step 4: reply with exactly what sg_check.py printed.")


def _squash(s):
    return re.sub(r"[^a-z0-9.]+", " ", (s or "").lower()).strip()


def render_doc(text, bad_lines, warn_lines):
    bad = [_squash(x) for x in bad_lines if x]
    warn = [_squash(x) for x in warn_lines if x]
    out = []
    for line in text.strip().splitlines():
        sq, safe = _squash(line), (html.escape(line) or "&nbsp;")
        if sq and any(b and (b in sq or sq in b) for b in bad):
            out.append(f'<span class="bad">{safe}</span>')
        elif sq and any(w and (w in sq or sq in w) for w in warn):
            out.append(f'<span class="warn">{safe}</span>')
        else:
            out.append(safe + "\n")
    return '<div class="doc">' + "".join(out) + "</div>"


def new_token(queue, label, documents):
    n = len(queue) + 1
    token, case_id = f"T-{n:03d}", f"tkn_{n:03d}"
    where = store.save(token, {"case_id": case_id, "label": label, "created_at": store.now_iso(),
                               "status": "WAITING", "documents": documents})
    queue.append({"token": token, "case_id": case_id, "label": label,
                  "status": "WAITING", "created": now()})
    save_queue(queue)
    return token, where


# ---------------------------------------------------------------- refresh statuses
queue = load_queue()
changed = False
for t in queue:
    if t["status"] == "CALLED":
        r = result_for(t["case_id"])
        if r:
            t["status"], t["result"] = "CHECKED", r["status"]
            changed = True
if changed:
    save_queue(queue)


def header():
    st.markdown("# 💊 ScriptGuard")
    st.caption("Discharge medication check on this machine. One chart at a time. "
               f"Patient store: {store.backend()}. Synthetic data, prototype only.")


# ---------------------------------------------------------------- intake screen
def show_intake():
    st.subheader("Submit a discharge for checking")
    label = st.text_input("Patient reference (no real names)", placeholder="e.g. Bed 12")
    c1, c2 = st.columns(2)
    with c1:
        up_s = st.file_uploader("Discharge summary (PDF, photo, scan, or text)",
                                type=list(intake.SUPPORTED), key="up_s")
        paste_s = st.text_area("...or paste it", height=160, key="paste_s")
    with c2:
        up_r = st.file_uploader("Prescription (PDF, photo, scan, or text)",
                                type=list(intake.SUPPORTED), key="up_r")
        paste_r = st.text_area("...or paste it", height=160, key="paste_r")

    if st.button("Get token", type="primary"):
        docs = {}
        for key, up, paste in (("discharge_summary", up_s, paste_s), ("prescription", up_r, paste_r)):
            try:
                if up is not None:
                    docs[key] = intake.from_bytes(up.getvalue(), up.name)
                elif paste and paste.strip():
                    docs[key] = intake.from_text(paste, key)
            except Exception as e:
                st.error(f"Could not read the {DOC_LABEL[key].lower()}: {e}")
        if len(docs) < 2:
            st.error("Add both documents: the discharge summary and the prescription.")
        else:
            token, where = new_token(queue, label, docs)
            st.markdown(f'<div class="serving">{token}</div>', unsafe_allow_html=True)
            st.success(f"Token {token} issued. Stored in {'MongoDB' if where == 'mongo' else 'local files'}.")
            for k, d in docs.items():
                low = d.get("low_confidence_numbers") or []
                st.caption(f"{DOC_LABEL[k]}: read via {d['method']}"
                           + (f", {len(low)} low-confidence number(s)" if low else ""))
            with st.expander("Text read from the documents (check it)"):
                for k, d in docs.items():
                    st.markdown(f"**{DOC_LABEL[k]}**")
                    st.text(d["text"])

    with st.expander("Queue a demo case (Person 2's synthetic documents)"):
        fmt = st.radio("Format", ["text", "pdf", "scan"], horizontal=True)
        root = config.DEMO_DIR / fmt
        cases = sorted(p.name for p in root.iterdir()) if root.exists() else []
        names = {"case_002": "case_002: warfarin stopped but ordered",
                 "case_003": "case_003: clean discharge", "case_004": "case_004: gabapentin 300 vs 3000 mg"}
        pick = st.selectbox("Case", cases, format_func=lambda c: names.get(c, c))
        if st.button("Queue this demo case") and pick:
            docs = {}
            for key in ("discharge_summary", "prescription"):
                f = next((p for p in (root / pick).iterdir() if p.stem == key), None)
                docs[key] = intake.from_bytes(f.read_bytes(), f.name)
            token, where = new_token(queue, f"demo {pick} ({fmt})", docs)
            st.success(f"Queued as {token} ({', '.join(d['method'] for d in docs.values())})")


# ---------------------------------------------------------------- pharmacist screen
def show_pharmacist():
    current = next((t for t in queue if t["status"] in ("CALLED", "CHECKED")), None)
    waiting = [t for t in queue if t["status"] == "WAITING"]
    if st.session_state.get("purged"):
        st.success(st.session_state.pop("purged"))

    a, b, c = st.columns([2, 2, 3])
    with a:
        st.markdown("Now serving")
        st.markdown(f'<div class="serving">{current["token"] if current else "--"}</div>',
                    unsafe_allow_html=True)
    with b:
        st.metric("Waiting", len(waiting))
        if st.button("Call next token", type="primary", disabled=bool(current) or not waiting):
            nxt = waiting[0]
            try:
                stage(nxt["token"], nxt["case_id"])
                store.update(nxt["token"], status="CALLED")
                nxt["status"], nxt["called"] = "CALLED", now()
                save_queue(queue)
                st.rerun()
            except Exception as e:
                st.error(f"Could not stage {nxt['token']}: {e}. Is the sandbox mounted at {config.SANDBOX_ROOT}?")
    with c:
        st.markdown("Charts the agent can see right now")
        st.code("\n".join(sandbox_contents()) or "(none)")
        st.button("Refresh")

    if not current:
        st.info("No token is being served. Click Call next token.")
        return

    cid = current["case_id"]
    rec = store.get(current["token"])
    if rec is None:
        st.error("This patient's record is missing from the store.")
        return
    r = result_for(cid)

    if not r:
        st.markdown('<div class="stamp WAIT">CHECKING</div>', unsafe_allow_html=True)
        st.markdown("**Send this to the agent** (OpenClaw chat, fresh session with `/new`), then click Refresh:")
        st.code(agent_prompt(cid), language=None)
        if st.button("Backup: run the same checks with the local model here"):
            import backup_runner
            with st.spinner("Extracting with the local model and checking..."):
                try:
                    backup_runner.run(cid, rec["documents"])
                    st.rerun()
                except Exception as e:
                    st.error(f"Local model call failed: {e}. Check `ollama ps` and the model name.")
    else:
        st.markdown(f'<div class="stamp {r["status"]}">{STAMP.get(r["status"], r["status"])}</div>',
                    unsafe_allow_html=True)
        st.caption(f"{r['message']}. Checked by the {r.get('source', 'agent')} run.")
        for cf in r["conflicts"]:
            if cf["type"] == "grounding_failed":
                st.markdown(f'<div class="finding review"><b>{TYPE_LABEL["grounding_failed"]}: '
                            f'{html.escape(cf["drug"])}</b>. {html.escape(cf["detail"])}</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="finding"><b>{TYPE_LABEL.get(cf["type"], cf["type"])}: '
                            f'{html.escape(cf["drug"])}</b>. Summary: {html.escape(str(cf["summary_value"]))}. '
                            f'Prescription: {html.escape(str(cf["order_value"]))}.</div>',
                            unsafe_allow_html=True)
        if r.get("evidence"):
            st.caption(f"Evidence: {r['evidence']}")

    bad_s, bad_p, warn = [], [], []
    if r:
        for cf in r["conflicts"]:
            if cf["type"] == "grounding_failed":
                warn.append(cf.get("source_text"))
            else:
                bad_s.append(cf.get("summary_text"))
                bad_p.append(cf.get("order_text"))
    d1, d2 = st.columns(2)
    for col, key, bad in ((d1, "discharge_summary", bad_s), (d2, "prescription", bad_p)):
        doc = rec["documents"][key]
        low = doc.get("low_confidence_numbers") or []
        col.markdown(f"**{DOC_LABEL[key]}**  \n<small>read via {doc['method']}"
                     + (f"; low-confidence numbers: {', '.join(str(x.get('word', x)) for x in low)}" if low else "")
                     + "</small>", unsafe_allow_html=True)
        col.markdown(render_doc(doc["text"], bad, warn), unsafe_allow_html=True)
        if doc.get("raw") and doc.get("mime", "").startswith("image/"):
            with col.expander("Original image"):
                st.image(doc["raw"])

    if r:
        st.markdown("#### Pharmacist decision")
        note = st.text_input("Note (for example the corrected dose)", key=f"n_{cid}")
        b1, b2, b3 = st.columns(3)
        decision = ("Approved as written" if b1.button("Approve as written") else
                    "Corrected and released" if b2.button("Correct and release") else
                    "Kept on hold" if b3.button("Keep on hold") else None)
        if decision:
            with open(config.AUDIT_FILE, "a") as log:   # no names, drugs, or document text
                log.write(json.dumps({
                    "token": current["token"], "result": r["status"],
                    "finding_types": sorted({c["type"] for c in r["conflicts"]}),
                    "decision": decision, "served_at": store.now_iso(),
                    "doc_fingerprints": [d.get("sha256") for d in rec["documents"].values()]}) + "\n")
            clear_dir(config.SANDBOX_CASES)
            removed = purge_patient(current["token"], cid)
            current.update(status="DONE", decision=decision, result=r["status"],
                           finished=now(), label="(deleted)")
            save_queue(queue)
            st.session_state["purged"] = (f"{current['token']} served ({decision}). Deleted: "
                                          + (", ".join(removed) or "nothing left to delete"))
            st.rerun()


# ---------------------------------------------------------------- board screen
def show_board():
    current = next((t for t in queue if t["status"] in ("CALLED", "CHECKED")), None)
    waiting = [t for t in queue if t["status"] == "WAITING"]
    b1, b2 = st.columns([3, 2])
    with b1:
        st.markdown("### Now serving")
        st.markdown(f'<div class="serving" style="font-size:9rem">{current["token"] if current else "--"}</div>',
                    unsafe_allow_html=True)
    with b2:
        st.markdown("### Next")
        for t in waiting[:5]:
            st.markdown(f'<span class="token">{t["token"]}</span>', unsafe_allow_html=True)
        if not waiting:
            st.write("No one waiting")
    st.divider()
    icon = {"WAITING": "⏳ Waiting", "CALLED": "🔍 Checking", "CHECKED": "🔍 Checking", "DONE": "✅ Done"}
    res = {"HELD": "🔴 held", "CLEAN": "🟢 passed", "NEEDS_REVIEW": "🟠 review"}
    for t in reversed(queue):
        r = result_for(t["case_id"])
        c1, c2, c3, c4 = st.columns([1, 2, 2, 3])
        c1.markdown(f'<span class="token">{t["token"]}</span>', unsafe_allow_html=True)
        c2.write(icon.get(t["status"], t["status"]))
        c3.write(res.get(r["status"] if r else t.get("result"), ""))
        c4.write(t.get("decision") or "")


# ---------------------------------------------------------------- routing
view = st.query_params.get("view", "all")
header()
if view == "intake":
    show_intake()
elif view == "board":
    show_board()
    time.sleep(3)
    st.rerun()
elif view == "pharmacist":
    show_pharmacist()
else:
    t1, t2, t3 = st.tabs(["Get a token", "Pharmacist", "Queue board"])
    with t1:
        show_intake()
    with t2:
        show_pharmacist()
    with t3:
        show_board()
