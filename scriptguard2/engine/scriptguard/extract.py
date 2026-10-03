"""Step 1: LLM extraction of medications into strict JSON.

Works with any OpenAI-compatible server (vLLM, Ollama, NIM). Configure with:
  SCRIPTGUARD_LLM_URL   default http://localhost:8000/v1   (Ollama: http://localhost:11434/v1)
  SCRIPTGUARD_LLM_MODEL default local-model
"""
import json
import os
import re
import urllib.request

from .schema import normalize_med

LLM_URL = os.environ.get("SCRIPTGUARD_LLM_URL", "http://localhost:8000/v1")
LLM_MODEL = os.environ.get("SCRIPTGUARD_LLM_MODEL", "local-model")

SYSTEM_PROMPT = """You extract medications from clinical documents. You never interpret, correct, or judge doses.

Return ONLY a JSON object of this exact form, with no other text:
{"medications": [{"drug": str, "dose": number or null, "unit": str or null,
  "frequency": str or null, "status": "continue" | "new" | "stop", "source_text": str}]}

Rules:
1. Extract every medication that is explicitly listed. Do not add medications that are not written.
2. "source_text" must be copied character-for-character from the document: the exact line or phrase
   the medication appears in. Do not paraphrase, fix typos, or reformat it.
3. "dose" is the number exactly as written in the document (3000 stays 3000, even if it looks wrong).
   Use null if no dose is written.
4. "unit" is the unit as written (mg, mcg, g, units, mL). Use null if missing.
5. "status": use "stop" if the document says to stop, discontinue, or hold the medication;
   "new" if it is newly started; otherwise "continue".
6. If the document is a discharge summary, extract from the discharge medication section and from any
   sentence that tells the patient to stop or change a medication.
7. If you are unsure about a value, still copy what is written. Never guess or calculate."""


def _call_llm(text, doc_type):
    user = f"Document type: {doc_type}\n\nDocument:\n<<<\n{text}\n>>>"
    body = {
        "model": LLM_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        f"{LLM_URL}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def _parse(raw):
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise
        obj = json.loads(m.group(0))
    meds = obj.get("medications", obj if isinstance(obj, list) else [])
    return [normalize_med(m) for m in meds if isinstance(m, dict)]


def extract(text, doc_type):
    """doc_type: 'discharge_summary' or 'orders'. Retries once if JSON is invalid."""
    last_err = None
    for _ in range(2):
        try:
            return _parse(_call_llm(text, doc_type))
        except (json.JSONDecodeError, KeyError) as e:
            last_err = e
    raise RuntimeError(f"Extraction failed after retry: {last_err}")
