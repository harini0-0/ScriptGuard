"""Run the verification suites and write reports/VERIFICATION_REPORT.md.
  python3 run_all.py                    # suites A-D (no model needed)
  python3 run_all.py --with-model text  # also suite E with the local model (text; add pdf scan if time allows)
  python3 run_all.py --report-only      # rebuild the report from saved results"""
import datetime
import json
import sys
from metrics import REPORTS, pct


def load(name):
    f = REPORTS / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else None


def suite_rows(names):
    out = []
    for n in names:
        d = load(n)
        if d:
            s = d["summary"]
            out.append(f"| {s['suite']} | {s['cases_scored']} | {s['errors_caught']}/{s['errors_planted']} ({pct(s['error_recall'])}) | "
                       f"{pct(s['precision'])} | {('%.3f' % s['f1']) if s['f1'] else 'n/a'} | {pct(s['specificity'])} | {s['false_alarms']} | "
                       f"{pct(s['review_rate'])} | {pct(s['case_accuracy'])} | "
                       f"{('%.2f s' % s['seconds_per_case']) if s['seconds_per_case'] is not None else 'n/a'} |")
    return out


def detail(name):
    d = load(name)
    if not d:
        return []
    s, rows = d["summary"], d["rows"]
    lines = [f"\n### {s['suite']}\n", "| Error type | Planted | Caught | Recall |", "|---|---|---|---|"]
    for t, v in sorted(s["per_type"].items()):
        lines.append(f"| {t} | {v['planted']} | {v['caught']} | {pct(v['caught'] / v['planted'] if v['planted'] else None)} |")
    lines += ["", "Status confusion (expected -> actual): " + ", ".join(f"{k}: {v}" for k, v in s["status_confusion"].items()),
              f"Advisory low flags raised: {s['advisory_low_flags']}. Excluded from scoring: {', '.join(s['cases_excluded']) or 'none'}."]
    bad = [r for r in rows if "error" in r or not r.get("correct")]
    if bad:
        lines += ["", "| Case | Scenario | Expected | Actual | Missed | False alarms | Note |", "|---|---|---|---|---|---|---|"]
        for r in bad:
            if "error" in r:
                lines.append(f"| {r['case']} | | | ERROR | | | {r['error'][:80]} |")
                continue
            note = (r.get("review_reason") or "")[:110]
            lines.append(f"| {r['case']} | {r['scenario']} | {r['expected_status']} | {r['status']} | "
                         f"{'; '.join(f'{a} {b}' for a, b in r['missed']) or '-'} | "
                         f"{'; '.join(f'{a} {b}' for a, b in r['false_alarms']) or '-'} | {note} |")
    return lines


def report():
    L = [f"# ScriptGuard verification report", "",
         f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M}. All documents are synthetic (fictional hospitals and patients).",
         "The product code is read, never modified. High flags hold an order; low flags are advisory and not scored.", "",
         "## Headline metrics", "",
         "| Suite | Cases | Errors caught | Precision | F1 | Specificity | False alarms | Sent to review | Case accuracy | Time/case |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    names = ["suite_a_checks_only", "suite_c_ocr_plus_checks_pdf", "suite_c_ocr_plus_checks_scan",
             "suite_e_end_to_end_text", "suite_e_end_to_end_pdf", "suite_e_end_to_end_scan"]
    L += suite_rows(names)
    if not any(load(n) for n in names[3:]):
        L += ["", "_Suite E (local Nemotron, end to end) not run yet: `python3 run_all.py --with-model text` on the GB10._"]

    L += ["", "## B. Reading fidelity (medication lines)", "",
          "| Format | Medication lines | Exact line | Found (≥0.92 similar, numbers exact) | Dose numbers exact | Approx. char error rate | Time/document |",
          "|---|---|---|---|---|---|---|"]
    for fmt in ("pdf", "scan"):
        d = load(f"suite_b_ocr_fidelity_{fmt}")
        if d:
            s = d["summary"]
            L.append(f"| {fmt} ({', '.join(s['methods'])}) | {s['medication_lines']} | {pct(s['line_exact_match'])} | "
                     f"{pct(s['line_found_ge_0.92_and_numbers_exact'])} | {pct(s['dose_numbers_exact'])} | "
                     f"{pct(s['approx_char_error_rate'])} | {s['seconds_per_document']:.2f} s |")
            wrong = [r for r in d["rows"] if not r["numbers_exact"]]
            for r in wrong:
                L.append(f"\n  Numeric OCR error ({fmt}, {r['case']}, {r['doc']}): `{r['gt']}` read as `{r['ocr']}`")

    d = load("suite_d_redaction")
    if d:
        s = d["summary"]
        L += ["", "## D. Identifier redaction before the sandbox", "",
              f"- Identifier instances checked: {s['identifier_instances_checked']} (name, UHID, DOB, address, PIN, phone, email)",
              f"- Leak rate with the name and MRN typed at intake: **{pct(s['leak_rate_with_intake_name_and_mrn'])}**",
              f"- Leak rate with pattern rules only: {pct(s['leak_rate_regex_only'])}",
              f"- Medication lines kept after redaction: **{pct(s['medication_lines_kept'])}** of {s['medication_lines_checked']}"]

    L += ["", "## Per-suite detail"]
    for n in names:
        L += detail(n)

    L += ["", "## How to read these results", "",
          "- **A** isolates the checking logic: hand-verified extractions on typed text.",
          "- **B** isolates reading: how faithfully PDFs and scans become text, measured on medication lines only.",
          "- **C** shows whether reading noise changes the verdict: verified extractions re-pointed to the lines the reader produced.",
          "- **D** checks that identifiers are removed before the chart enters the sandbox without removing medicines.",
          "- **E** is the honest end-to-end number: reading + local Nemotron extraction + checks.", "",
          "## Known limitations", "",
          "- Small synthetic test set (20 cases); results show behaviour, not clinical accuracy. Validate on de-identified real data before any deployment.",
          "- case_005 (a home medication silently dropped) is out of scope: it needs the home medication list as a third document.",
          "- case_011: a salt-form change (metoprolol succinate in the summary, tartrate on the prescription) raises the planted 'missing' flag and also a 'not in summary' flag for tartrate. Scored strictly as one false alarm; it is the same error seen from both sides.",
          "- case_003 (scan): OCR read '500 mg' as 'S00 mg'. Grounding could not verify the dose, so the case went to 'check by hand' instead of a wrong verdict. Scored as not correct (it lowers specificity), but it is the intended safe behaviour.",
          "- Suite C assumes a perfect extractor working on the reader's output; suite E measures the real model.",
          "- Model output can vary between runs; rerun suite E to see run-to-run spread.",
          "- Brand-name coverage is a curated list (about 50 brands); unknown brands fall back to the printed name."]
    (REPORTS / "VERIFICATION_REPORT.md").write_text("\n".join(L) + "\n")
    print("wrote", REPORTS / "VERIFICATION_REPORT.md")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--report-only" not in args:
        import suite_a_checks_only, suite_b_ocr_fidelity, suite_c_ocr_plus_checks, suite_d_redaction
        suite_a_checks_only.run(); suite_b_ocr_fidelity.run(); suite_c_ocr_plus_checks.run(); suite_d_redaction.run()
        if "--with-model" in args:
            import suite_e_end_to_end
            fmts = tuple(a for a in args if a in ("text", "pdf", "scan")) or ("text",)
            suite_e_end_to_end.run(fmts)
    report()
