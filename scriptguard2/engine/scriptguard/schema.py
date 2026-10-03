"""Shared contract constants and normalization helpers.

Keep these in sync with the team contract:
  extraction item: drug, dose, unit, frequency, status, source_text
  result status:   CLEAN | HELD | NEEDS_REVIEW
  conflict types:  dose_mismatch | stopped_but_ordered | missing_from_orders | grounding_failed
"""
import re

MED_STATUSES = {"continue", "new", "stop"}
RESULT_STATUSES = {"CLEAN", "HELD", "NEEDS_REVIEW"}
CONFLICT_TYPES = {"dose_mismatch", "stopped_but_ordered", "missing_from_orders", "grounding_failed"}

# Unit normalization: everything mass-based is compared in mg.
UNIT_ALIASES = {
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "mcg": "mcg", "ug": "mcg", "µg": "mcg", "microgram": "mcg", "micrograms": "mcg",
    "g": "g", "gram": "g", "grams": "g",
    "unit": "units", "units": "units", "u": "units", "iu": "units",
    "ml": "mL", "milliliter": "mL", "milliliters": "mL",
    "meq": "mEq", "milliequivalent": "mEq", "milliequivalents": "mEq",
}
TO_MG = {"mg": 1.0, "mcg": 0.001, "g": 1000.0}

# Tiny brand -> generic map for the demo. Replace with RxNorm lookups later.
BRAND_TO_GENERIC = {
    "neurontin": "gabapentin",
    "coumadin": "warfarin", "jantoven": "warfarin",
    "glucophage": "metformin",
    "lipitor": "atorvastatin",
    "prinivil": "lisinopril", "zestril": "lisinopril",
    "lasix": "furosemide",
    "eliquis": "apixaban",
    "lantus": "insulin glargine",
}


def norm_drug(name):
    if not name:
        return ""
    n = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
    n = re.sub(r"\s+", " ", n).strip()
    return BRAND_TO_GENERIC.get(n, n)


def norm_unit(unit):
    if not unit:
        return None
    return UNIT_ALIASES.get(str(unit).strip().lower(), str(unit).strip())


def norm_status(status):
    s = str(status or "continue").strip().lower()
    if s in {"stop", "stopped", "discontinue", "discontinued", "hold", "held"}:
        return "stop"
    if s in {"new", "start", "started"}:
        return "new"
    return "continue"


def to_number(dose):
    """Parse 300, '300', '3,000', '0.5' -> float. Returns None if not a number."""
    if dose is None:
        return None
    if isinstance(dose, (int, float)):
        return float(dose)
    m = re.search(r"\d[\d,]*\.?\d*", str(dose))
    return float(m.group(0).replace(",", "")) if m else None


def comparable_dose(dose, unit):
    """Return (value, unit_family) so mg/mcg/g compare correctly."""
    value = to_number(dose)
    u = norm_unit(unit)
    if value is None:
        return None, u
    if u in TO_MG:
        return round(value * TO_MG[u], 6), "mass"
    return value, u


def normalize_med(med):
    """Clean one extracted item into the contract shape."""
    return {
        "drug": norm_drug(med.get("drug")),
        "dose": to_number(med.get("dose")),
        "unit": norm_unit(med.get("unit")),
        "frequency": (med.get("frequency") or None),
        "status": norm_status(med.get("status")),
        "source_text": (med.get("source_text") or "").strip(),
    }
