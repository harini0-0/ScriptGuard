"""Backup path: Person 2's extraction prompt (+ table rules) against local Ollama, then the same
checks as the agent tool. Writes the result where the dashboard reads agent results."""
import json
import os
import re

import config
os.environ.setdefault("SCRIPTGUARD_LLM_URL", config.OLLAMA_V1)
os.environ.setdefault("SCRIPTGUARD_LLM_MODEL", config.MODEL)
import realworld                                   # noqa: E402
from scriptguard import extract as p2extract      # noqa: E402
from scriptguard.pipeline import check_extraction  # noqa: E402

p2extract.SYSTEM_PROMPT = p2extract.SYSTEM_PROMPT + realworld.EXTRA_RULES


def _raw_meds(text, doc_type):
    """Model output WITHOUT normalization (keeps brand names for the brand check). One retry."""
    for _ in range(2):
        try:
            raw = re.sub(r"```(?:json)?", "", p2extract._call_llm(text, doc_type)).strip()
            m = re.search(r"\{.*\}", raw, re.S)
            obj = json.loads(m.group(0) if m else raw)
            meds = obj.get("medications", obj if isinstance(obj, list) else [])
            return [x for x in meds if isinstance(x, dict)]
        except (json.JSONDecodeError, KeyError, AttributeError):
            continue
    raise RuntimeError("The local model did not return valid JSON twice.")


def run(case_id, documents):
    """documents: staged (redacted) {doc_type: {text, method, low_confidence_numbers, file}}"""
    docs = {k: {f: documents[k][f] for f in ("text", "method", "low_confidence_numbers", "file")}
            for k in ("discharge_summary", "prescription")}
    raw = {k: _raw_meds(docs[k]["text"], k) for k in docs}
    extraction = {"case_id": case_id, "documents": {k: dict(docs[k], medications=raw[k]) for k in docs}}
    evidence = json.loads((config.ENGINE_DIR / "evidence.json").read_text())
    result = realworld.build_flags(check_extraction(extraction, evidence_db=evidence), raw, docs)
    result["source"] = "host backup"
    config.SANDBOX_RESULTS.mkdir(parents=True, exist_ok=True)
    out = config.SANDBOX_RESULTS / f"{case_id}.json"
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(result, indent=2))
    os.replace(tmp, out)
    return result
