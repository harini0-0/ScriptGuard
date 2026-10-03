"""Real-world layer on top of Person 2's engine (standard library only for the sandbox parts).

Importing this module patches the engine so it handles hospital paperwork like Indian discharge
summaries: TAB/CAP prefixes, brand and combination names, OCR-split names ("P AND" for "PAN D"),
1-0-1 schedules, doses without units, and rotated scans. It also builds dashboard flags.
"""
import re
from difflib import SequenceMatcher

from scriptguard import schema

# ------------------------------------------------------------------ drug names
FORM_PREFIX = re.compile(
    r"^\s*(?:\d+[.)]\s*)?(?:tab(?:let)?s?|cap(?:sule)?s?|inj(?:ection)?|syp|syr(?:up)?|susp|"
    r"oint(?:ment)?|gel|drops?|neb|sachet|t|c)\b\.?\s*", re.I)

# Keys are "squashed": lowercase letters and digits only, so OCR spacing noise does not matter.
BRANDS = {
    "augmentin": "amoxicillin+clavulanate", "moxclav": "amoxicillin+clavulanate",
    "clavam": "amoxicillin+clavulanate", "hifenacp": "aceclofenac+paracetamol",
    "zerodolp": "aceclofenac+paracetamol", "hifenac": "aceclofenac", "zerodol": "aceclofenac",
    "pand": "pantoprazole+domperidone", "pantopd": "pantoprazole+domperidone",
    "pan": "pantoprazole", "pan40": "pantoprazole", "pantop": "pantoprazole", "pantocid": "pantoprazole",
    "limcee": "ascorbic acid", "celin": "ascorbic acid",
    "dolo": "paracetamol", "dolo650": "paracetamol", "crocin": "paracetamol", "calpol": "paracetamol",
    "pcm": "paracetamol", "acetaminophen": "paracetamol",
    "ultracet": "tramadol+paracetamol", "combiflam": "ibuprofen+paracetamol",
    "shelcal": "calcium+vitamin d3", "ecosprin": "aspirin", "telma": "telmisartan",
    "glycomet": "metformin", "thyronorm": "levothyroxine", "eltroxin": "levothyroxine",
    "emeset": "ondansetron", "ondem": "ondansetron", "taximo": "cefixime", "zifi": "cefixime",
    "monocef": "ceftriaxone", "azee": "azithromycin", "azithral": "azithromycin",
    "clexane": "enoxaparin", "nexpro": "esomeprazole", "razo": "rabeprazole", "rablet": "rabeprazole",
    "montairlc": "montelukast+levocetirizine", "neurobionforte": "vitamin b complex",
    "becosules": "vitamin b complex", "chymoralforte": "trypsin+chymotrypsin",
    "storvas": "atorvastatin", "amlong": "amlodipine", "stamlo": "amlodipine",
}
_GENERICS = set(BRANDS.values()) | {"paracetamol", "pantoprazole", "amoxicillin", "aceclofenac"}


def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean_name(raw):
    """'TAB PAN D 40MG' -> 'pan d'; strips dosage form, strength, and OCR punctuation."""
    n = FORM_PREFIX.sub("", str(raw or ""))
    n = re.sub(r"\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|units?)\b.*$", "", n, flags=re.I)
    n = re.sub(r"[^A-Za-z0-9+\- ]", " ", n)
    return re.sub(r"\s+", " ", n).strip().lower()


def _tokens(name):
    name = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", name)   # "p1-0-1x7days" -> "p 1-0-1 x 7 days"
    return [t for t in re.split(r"[\s\-]+", name) if t and not re.search(r"\d", t)]


def canonical(raw):
    """Generic name used for matching across documents (OCR-tolerant)."""
    name = clean_name(raw)
    if not name:
        return ""
    toks = _tokens(name)
    full_sq = squash(name)
    if full_sq in BRANDS:
        return BRANDS[full_sq]
    for n in range(min(3, len(toks)), 0, -1):          # brand on the leading words: "augmentin oe z"
        sq = squash("".join(toks[:n]))
        if sq in BRANDS:
            return BRANDS[sq]
    words = [t for t in toks if len(t) >= 3] or toks
    joined = " ".join(words)
    old = schema.BRAND_TO_GENERIC.get(joined)
    if old:
        return old
    if words:                                           # OCR-misspelled brand: near-identical only
        sq = squash(words[0])
        best = max(BRANDS, key=lambda k: SequenceMatcher(None, sq, k).ratio())
        if len(sq) >= 5 and SequenceMatcher(None, sq, best).ratio() >= 0.88:
            return BRANDS[best]
    return joined


def _comparable_dose(dose, unit):
    value = schema.to_number(dose)
    u = schema.norm_unit(unit)
    if value is None:
        return None, u
    if u in schema.TO_MG:
        return round(value * schema.TO_MG[u], 6), "mass"
    if u is None:            # "Dolo 650": strength printed without a unit is a mass in mg
        return value, "mass"
    return value, u


# Patch Person 2's engine (normalize_med and compare look these up at call time)
schema.norm_drug = canonical
schema.comparable_dose = _comparable_dose
from scriptguard import compare as _compare  # noqa: E402
_compare.comparable_dose = _comparable_dose


# ------------------------------------------------------------------ schedules
def per_day(freq):
    """'1-0-1' -> 2, 'BD' -> 2, 'TDS' -> 3, 'OD' -> 1, 'SOS' -> 'prn'. None if unknown."""
    f = (freq or "").lower()
    m = re.search(r"\b(\d)\s*-\s*(\d)\s*-\s*(\d)(?:\s*-\s*(\d))?\b", f)
    if m:
        return sum(int(x) for x in m.groups() if x)
    table = [(r"\b(sos|prn|as needed|when required)\b", "prn"),
             (r"\b(qid|q6h|four times)\b", 4), (r"\b(tds|tid|q8h|thrice|three times)\b", 3),
             (r"\b(bd|bid|q12h|twice|two times)\b", 2),
             (r"\b(od|qd|once|daily|every day|hs|at night|bedtime|nightly|morning)\b", 1)]
    for pat, val in table:
        if re.search(pat, f):
            return val
    return None


# ------------------------------------------------------------------ OCR: auto-rotate scans
MED_LINE = re.compile(r"\d+\s*(?:mg|mcg|ml|iu)\b|\b\d\s*-\s*\d\s*-\s*\d\b|\b(?:tab|cap|inj|syp)\b", re.I)


def patch_ocr_rotation():
    """Host only: normalize page size, OCR with table and prose layouts, keep the better reading."""
    from scriptguard import ingest
    if getattr(ingest, "_rotation_patched", False):
        return
    import pytesseract
    from PIL import ImageFilter, ImageOps

    def _ocr_once(img, psm):
        data = pytesseract.image_to_data(img, config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
        lines, low = {}, []
        for i, word in enumerate(data["text"]):
            if not word.strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(word)
            conf = float(data["conf"][i])
            if re.search(r"\d", word) and 0 <= conf < ingest.LOW_CONF:
                low.append({"word": word, "confidence": round(conf, 1)})
        text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
        return ingest.fix_ocr_confusions(text), low

    def _ocr_image_robust(img):
        """Normalize size (~300 dpi A4), then try three readings and keep the most medication-like."""
        gray = ImageOps.autocontrast(img.convert("L"))
        target = 2480
        if abs(gray.width - target) > 300:
            scale = target / gray.width
            gray = gray.resize((target, max(1, int(gray.height * scale))))
        clean = gray.filter(ImageFilter.MedianFilter(3))
        binar = clean.point(lambda v: 255 if v > 150 else 0)
        best = None
        for variant, psm in ((binar, 6), (clean, 6), (clean, 4)):
            text, low = _ocr_once(variant, psm)
            lines = text.splitlines()
            score = (sum(bool(re.search(r"\b\d\s*-\s*\d\s*-\s*\d\b", l)) for l in lines) * 2
                     + sum(bool(MED_LINE.search(l)) for l in lines) - 0.2 * len(low))
            if best is None or score > best[0]:
                best = (score, text, low)
        return best[1], best[2]

    ingest._ocr_image = _ocr_image_robust
    ingest._rotation_patched = True


# ------------------------------------------------------------------ redaction (host, before staging)
ID_LINE = re.compile(r"\b(uhid|mrn|ip\s*no|op\s*no|patient\s*name|name\s*:|address|dob|date of birth|"
                     r"ph(?:one)?\s*[:.]|mobile|e-?mail|aadhaar|bed\s*no|age\s*:)", re.I)
INLINE = [
    (re.compile(r"\b(?:UHID|UH|MRN|IP\s*No\.?)\s*[:\-]?\s*[A-Z0-9]{4,}", re.I), "[ID]"),
    (re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Master|Baby)\.?\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}"), "[PATIENT]"),
    (re.compile(r"\bDOB\s*:?\s*\d{1,2}\s*[A-Za-z]{3,9}\s*\d{4}", re.I), "[DOB]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)"), "[NUMBER]"),
]


def redact(text, name=None, mrn=None):
    """Remove identifiers so the agent never sees who the patient is. Medication lines are kept."""
    out = []
    for line in (text or "").splitlines():
        low = line.lower()
        has_med = re.search(r"\d+\s*(mg|mcg|g|ml|iu|units?)\b|\b\d-\d-\d\b", low)
        if ID_LINE.search(line) and not has_med and len(line) < 240:
            out.append("[REDACTED: patient identifiers]")
            continue
        for pat, repl in INLINE:
            if not has_med or repl in ("[ID]", "[PATIENT]", "[EMAIL]", "[DOB]"):
                line = pat.sub(repl, line)
        out.append(line)
    text = "\n".join(out)
    for value in filter(None, [mrn, name] + (name.split() if name else [])):
        if len(value.strip()) >= 3:
            text = re.sub(re.escape(value.strip()), "[PATIENT]", text, flags=re.I)
    return text


# ------------------------------------------------------------------ dashboard flags
def _line_no(text, src):
    if not src:
        return None
    lines = [l for l in (text or "").splitlines()]
    s = squash(src)
    for i, l in enumerate(lines, 1):
        sl = squash(l)
        if s and sl and (s in sl or SequenceMatcher(None, s, sl[:len(s) + 4]).ratio() > 0.9):
            return i
    return None


def _dose_sentence(c):
    sv, ov = schema.to_number(c.get("summary_value")), schema.to_number(c.get("order_value"))
    drug = c["drug"]
    if sv and ov:
        r = ov / sv
        words = {2: "doubles", 3: "triples", 0.5: "halves"}
        for k, w in words.items():
            if abs(r - k) < 1e-6:
                return f"The prescription {w} the {drug} dose written in the summary ({c['summary_value']} vs {c['order_value']})."
        if r >= 1.5 and abs(r - round(r)) < 1e-6:
            return f"The prescription has {int(round(r))} times the {drug} dose written in the summary ({c['summary_value']} vs {c['order_value']})."
    return f"The {drug} dose differs: summary {c['summary_value']}, prescription {c['order_value']}."


def _per_day_words(f):
    n = per_day(f)
    return {1: "once daily", 2: "twice daily", 3: "three times daily", 4: "four times daily",
            "prn": "as needed"}.get(n, "")


def build_flags(result, raw_extraction, documents):
    """Add HTML-dashboard fields to a Person 2 result: flags, checked, review_reason.
    raw_extraction: {"discharge_summary": [meds], "prescription": [meds]} as the model returned them.
    documents: {"discharge_summary": {"text"...}, "prescription": {"text"...}}"""
    s_text = documents["discharge_summary"]["text"]
    p_text = documents["prescription"]["text"]
    flags = []
    label = {"dose_mismatch": "dose_mismatch", "stopped_but_ordered": "stopped_in_summary_but_prescribed",
             "missing_from_orders": "missing_from_prescription"}
    review = []
    for c in result["conflicts"]:
        if c["type"] == "grounding_failed":
            review.append(f"{c['drug']}: {c['detail']}")
            continue
        if c["type"] == "dose_mismatch":
            exp = _dose_sentence(c)
        elif c["type"] == "stopped_but_ordered":
            exp = f"{c['drug'].capitalize()} is stopped in the summary but still on the prescription ({c['order_value']})."
        else:
            exp = f"{c['drug'].capitalize()} is continued in the summary but not on the prescription."
        flags.append({"severity": "HIGH", "drug": c["drug"], "type": label.get(c["type"], c["type"]),
                      "explanation": exp, "s": c.get("summary_text"), "sl": _line_no(s_text, c.get("summary_text")),
                      "p": c.get("order_text") or None, "pl": _line_no(p_text, c.get("order_text"))})

    s_raw = [m for m in raw_extraction.get("discharge_summary", []) if isinstance(m, dict)]
    p_raw = [m for m in raw_extraction.get("prescription", []) if isinstance(m, dict)]
    s_by = {canonical(m.get("drug")): m for m in s_raw if m.get("drug")}
    p_by = {canonical(m.get("drug")): m for m in p_raw if m.get("drug")}
    flagged = {f["drug"] for f in flags} | {c["drug"] for c in result["conflicts"]}

    for drug, p in p_by.items():          # ordered but never planned
        if drug and drug not in s_by and drug not in flagged:
            flags.append({"severity": "HIGH", "drug": drug, "type": "not_in_summary",
                          "explanation": f"{p.get('drug')} is on the prescription but not in the discharge summary. Confirm it was intended.",
                          "s": None, "sl": None, "p": p.get("source_text"), "pl": _line_no(p_text, p.get("source_text"))})
    for drug, s in s_by.items():
        p = p_by.get(drug)
        if not p or drug in flagged or s.get("status") == "stop":
            continue
        fs, fp = per_day(s.get("frequency") or s.get("source_text")), per_day(p.get("frequency") or p.get("source_text"))
        if fs is not None and fp is not None and fs != fp:
            flags.append({"severity": "HIGH", "drug": drug, "type": "frequency_mismatch",
                          "explanation": f"The summary says {s.get('frequency')} ({_per_day_words(s.get('frequency'))}); "
                                         f"the prescription says {p.get('frequency')} ({_per_day_words(p.get('frequency'))}).",
                          "s": s.get("source_text"), "sl": _line_no(s_text, s.get("source_text")),
                          "p": p.get("source_text"), "pl": _line_no(p_text, p.get("source_text"))})
        elif squash(clean_name(s.get("drug"))) != squash(clean_name(p.get("drug"))):
            flags.append({"severity": "LOW", "drug": drug, "type": "name_differs_confirm_brand_intent",
                          "explanation": f"Summary names {s.get('drug')}, prescription names {p.get('drug')}. "
                                         f"Same medicine ({drug}). Confirm whether the brand was intended.",
                          "s": s.get("source_text"), "sl": _line_no(s_text, s.get("source_text")),
                          "p": p.get("source_text"), "pl": _line_no(p_text, p.get("source_text"))})

    if any(f["severity"] == "HIGH" for f in flags) and result["status"] == "CLEAN":
        result["status"], result["message"] = "HELD", "Flagged for pharmacist review: medication mismatch found"
    result["flags"] = flags
    result["checked"] = len({canonical(m.get("drug")) for m in s_raw if m.get("drug")})
    result["review_reason"] = ("Some values could not be matched to the document. Check the originals by hand: "
                               + "; ".join(review)) if review else None
    return result


EXTRA_RULES = """
8. Tables (MEDICINE | DOSAGE | FREQUENCY | SCHEDULE | DURATION): one medication per table row.
   source_text is the whole row exactly as printed, e.g. "TAB AUGMENTIN 625MG 1TAB 1-0-1 3DAYS".
   drug is the name as printed without TAB/CAP (e.g. "AUGMENTIN", "PAN D"); keep brand names.
   frequency is the schedule as printed (e.g. "1-0-1", "BD", "TDS"). If the DOSAGE cell is empty, dose is null.
9. Ignore headers, addresses, vitals, lab values, phone numbers, and footers. Lines marked [REDACTED] are not medicines.
10. If OCR garbled a name (e.g. "P AND ¢"), copy it exactly as printed; never fix it."""
