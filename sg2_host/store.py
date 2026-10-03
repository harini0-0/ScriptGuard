"""Patient store on the HOST. MongoDB (scriptguard.discharges, _id = token) when reachable,
otherwise JSON files in sg2_host/data/patients. The sandbox never touches this."""
import base64
import datetime
import json
import os
import time

from config import LOCAL_STORE

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
_client, _down_until = None, 0.0


def _col():
    global _client, _down_until
    if time.time() < _down_until:
        return None
    try:
        from pymongo import MongoClient
        if _client is None:
            _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
        _client.admin.command("ping")
        return _client["scriptguard"]["discharges"]
    except Exception:
        _client, _down_until = None, time.time() + 30
        return None


def backend():
    return "MongoDB (local)" if _col() is not None else "local files (MongoDB not reachable)"


def save(token, record):
    """record: {case_id, label, created_at, status, documents: {doc_type: {...}}}
    each document: text, method, low_confidence_numbers, file, sha256, raw (bytes or None), mime"""
    record = dict(record, _id=token)
    col = _col()
    if col is not None:
        from bson.binary import Binary
        rec = json.loads(json.dumps(record, default=str))  # shallow copy without bytes issues
        for k, d in record["documents"].items():
            rec["documents"][k]["raw"] = Binary(d["raw"]) if d.get("raw") else None
        col.replace_one({"_id": token}, rec, upsert=True)
        return "mongo"
    LOCAL_STORE.mkdir(parents=True, exist_ok=True)
    rec = json.loads(json.dumps(record, default=str))
    for k, d in record["documents"].items():
        rec["documents"][k]["raw"] = base64.b64encode(d["raw"]).decode() if d.get("raw") else None
    (LOCAL_STORE / f"{token}.json").write_text(json.dumps(rec))
    return "local"


def get(token):
    col = _col()
    if col is not None:
        rec = col.find_one({"_id": token})
        if rec:
            for d in rec["documents"].values():
                d["raw"] = bytes(d["raw"]) if d.get("raw") else None
            return rec
    f = LOCAL_STORE / f"{token}.json"
    if f.exists():
        rec = json.loads(f.read_text())
        for d in rec["documents"].values():
            d["raw"] = base64.b64decode(d["raw"]) if d.get("raw") else None
        return rec
    return None


def update(token, **fields):
    col = _col()
    if col is not None:
        col.update_one({"_id": token}, {"$set": fields})
    f = LOCAL_STORE / f"{token}.json"
    if f.exists():
        rec = json.loads(f.read_text())
        rec.update(fields)
        f.write_text(json.dumps(rec, default=str))


def delete(token):
    """Remove every stored copy of this patient's documents. Returns where it deleted from."""
    gone = []
    col = _col()
    if col is not None and col.delete_one({"_id": token}).deleted_count:
        gone.append("MongoDB record")
    f = LOCAL_STORE / f"{token}.json"
    if f.exists():
        f.unlink()
        gone.append("local record")
    return gone


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")
