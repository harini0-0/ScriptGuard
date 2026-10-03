"""Step 3: deterministic comparison of discharge summary vs orders. No AI here."""
from difflib import SequenceMatcher

from .schema import comparable_dose

FUZZY_NAME = 0.92   # "hydrochliorothiazide" ~ "hydrochlorothiazide", but not "metoprolol tartrate" ~ "succinate"


def _match_name(drug, names):
    if drug in names:
        return drug
    best = max(names, key=lambda n: SequenceMatcher(None, drug, n).ratio(), default=None)
    if best and len(drug) >= 6 and SequenceMatcher(None, drug, best).ratio() >= FUZZY_NAME:
        return best
    return None


def _fmt(med):
    if med.get("dose") is None:
        return "no dose"
    d = med["dose"]
    d = int(d) if float(d).is_integer() else d
    return f"{d} {med.get('unit') or ''}".strip()


def _index(meds):
    """One entry per drug. If a drug is mentioned twice (e.g. once in prose without a dose,
    once in the medication list), prefer a stop instruction, then the entry that has a dose."""
    out = {}
    for m in meds:
        d = m.get("drug")
        if not d:
            continue
        cur = out.get(d)
        if cur is None:
            out[d] = m
        elif m.get("status") == "stop" and cur.get("status") != "stop":
            out[d] = m
        elif cur.get("status") != "stop" and cur.get("dose") is None and m.get("dose") is not None:
            out[d] = m
    return out


def compare(summary_meds, order_meds):
    conflicts = []
    orders = _index(order_meds)
    for drug, s in _index(summary_meds).items():
        key = _match_name(drug, list(orders))
        o = orders.get(key) if key else None
        ordered = o is not None and o.get("status") != "stop"

        if s["status"] == "stop":
            if ordered:
                conflicts.append({
                    "type": "stopped_but_ordered", "drug": drug,
                    "summary_value": "stop", "order_value": _fmt(o),
                    "summary_text": s["source_text"], "order_text": o["source_text"],
                })
            continue

        if not ordered:
            conflicts.append({
                "type": "missing_from_orders", "drug": drug,
                "summary_value": _fmt(s), "order_value": "not ordered",
                "summary_text": s["source_text"], "order_text": "",
            })
            continue

        sv, su = comparable_dose(s.get("dose"), s.get("unit"))
        ov, ou = comparable_dose(o.get("dose"), o.get("unit"))
        if sv is None or ov is None:
            continue  # missing dose on one side: grounding/review handles it
        if su != ou or abs(sv - ov) > 1e-6:
            conflicts.append({
                "type": "dose_mismatch", "drug": drug,
                "summary_value": _fmt(s), "order_value": _fmt(o),
                "summary_text": s["source_text"], "order_text": o["source_text"],
            })
    return conflicts
