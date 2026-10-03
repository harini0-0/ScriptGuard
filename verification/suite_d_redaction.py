"""Suite D: identifiers removed before the sandbox, medication lines kept."""
import json
from metrics import DATA, KEY, REPORTS, realworld

realworld.patch_ocr_rotation()
from scriptguard.ingest import to_text  # noqa: E402

MOCKS = json.loads((DATA / "mocks.json").read_text())
IDENTIFIERS = ["ANJALI", "RAO", "1800012345", "12 Mar 1995", "14 LAKE VIEW", "411001", "020 4000 1234",
               "info@lakeview.example"]


def leaks(text):
    t = text.upper()
    return [i for i in IDENTIFIERS if i.upper() in t]


def run():
    rows = []
    for fmt in ("text", "scan"):
        for case in ("realistic_held", "realistic_clean"):
            for d in ("discharge_summary", "prescription"):
                f = next(p for p in (DATA / fmt / case).iterdir() if p.stem == d)
                text = to_text(f)["text"]
                present = leaks(text)
                with_form = realworld.redact(text, name="Anjali Rao", mrn="1800012345")
                regex_only = realworld.redact(text)
                rows.append({"format": fmt, "case": case, "doc": d, "identifiers_present": len(present),
                             "leaked_with_intake_name_mrn": leaks(with_form), "leaked_regex_only": leaks(regex_only)})
    kept, total, lost = 0, 0, []
    for case in sorted(KEY):
        for d in ("discharge_summary", "prescription"):
            text = (DATA / "text" / case / f"{d}.txt").read_text()
            red = realworld.redact(text)
            for m in MOCKS[case][d]:
                total += 1
                if m["source_text"] in red:
                    kept += 1
                else:
                    lost.append([case, d, m["source_text"]])
    present = sum(r["identifiers_present"] for r in rows)
    summary = {
        "identifier_instances_checked": present,
        "leak_rate_with_intake_name_and_mrn": sum(len(r["leaked_with_intake_name_mrn"]) for r in rows) / present if present else None,
        "leak_rate_regex_only": sum(len(r["leaked_regex_only"]) for r in rows) / present if present else None,
        "medication_lines_checked": total, "medication_lines_kept": kept / total if total else None,
        "medication_lines_lost": lost,
    }
    (REPORTS / "suite_d_redaction.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    return summary, rows


if __name__ == "__main__":
    s, rows = run()
    print(json.dumps(s, indent=1))
    for r in rows:
        if r["leaked_with_intake_name_mrn"] or r["leaked_regex_only"]:
            print(r)
