"""Step 2: grounding. Every extracted value must be traceable to the source text.

A medication fails grounding if:
  - its source_text does not appear in the document, or
  - its dose number does not appear inside its source_text.
Failures are returned as grounding_failed conflicts; the pipeline then routes to NEEDS_REVIEW.
"""
import re
from difflib import SequenceMatcher

from .schema import to_number

FUZZY_LINE = 0.92   # similarity needed to accept a line with small OCR letter errors


def _squash(s):
    """Lowercase, drop stray punctuation (OCR speckle, bullets), keep decimal points inside numbers."""
    s = (s or "").lower()
    s = re.sub(r"(?<=\d)\.(?=\d)", "\x00", s)    # protect decimal points (0.1)
    s = re.sub(r"(?<=\d),(?=\d)", "", s)          # 1,000 -> 1000
    s = re.sub(r"[^a-z0-9\x00]+", " ", s)
    s = s.replace("\x00", ".").replace("i", "l")   # OCR confuses I and l; letters only, never digits
    return re.sub(r"\s+", " ", s).strip()


def _numbers_in(text):
    return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")}


def _digits(s):
    return re.findall(r"\d+(?:\.\d+)?", s)


def _found(src, doc, doc_lines):
    """Exact match after normalization, or a near-identical line whose numbers match exactly."""
    if src in doc:
        return True
    for line in doc_lines:
        window = line[:len(src) + 8]
        if _digits(window) and _digits(src) == _digits(window)[:len(_digits(src))] and \
                SequenceMatcher(None, src, window[:len(src)]).ratio() >= FUZZY_LINE:
            return True
    return False


def ground(meds, text, doc_label="document"):
    failures = []
    doc = _squash(text)
    doc_lines = [_squash(l) for l in (text or "").splitlines() if l.strip()]
    for med in meds:
        src = med.get("source_text", "")
        problem = None
        if not src:
            problem = "no source text returned by extractor"
        elif not _found(_squash(src), doc, doc_lines):
            problem = "source text not found in document"
        elif med.get("dose") is not None and to_number(med["dose"]) not in _numbers_in(src):
            problem = f"dose {med['dose']} not found in source text"
        if problem:
            failures.append({
                "type": "grounding_failed",
                "drug": med.get("drug", ""),
                "detail": f"{doc_label}: {problem}",
                "source_text": src,
            })
    return failures
