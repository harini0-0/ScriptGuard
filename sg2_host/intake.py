"""Turn an uploaded file (or pasted text) into Person 2's ingest format, on the HOST."""
import hashlib
import mimetypes
import tempfile
from pathlib import Path

import config  # noqa: F401  (puts the engine on sys.path)
import realworld
from scriptguard.ingest import to_text

realworld.patch_ocr_rotation()   # size-normalized, table-aware OCR

SUPPORTED = ("pdf", "png", "jpg", "jpeg", "tif", "tiff", "txt")


def from_bytes(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower() or ".txt"
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / f"upload{suffix}"
        p.write_bytes(data)
        doc = to_text(p)          # pdf text layer, scanned-pdf OCR, image OCR, or plain text
    doc["file"] = filename
    doc["sha256"] = hashlib.sha256(data).hexdigest()
    doc["mime"] = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    doc["raw"] = data
    return doc


def from_text(text: str, label: str):
    data = text.encode()
    return {"text": text, "method": "text", "low_confidence_numbers": [], "file": f"{label}.txt",
            "sha256": hashlib.sha256(data).hexdigest(), "mime": "text/plain", "raw": None}
