"""HTML view of the doctor export, for reading in a browser or printing.

A doctor with no app needs something readable, and a browser's own Print dialog
produces a PDF without any server-side renderer. This is the fallback that always
works, including on machines where a PDF library has no system dependencies.
"""

from html import escape

from app.services.doctor_export import DoctorExport

_STYLE = """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 32px 20px 56px;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #0c1110; background: #fff; line-height: 1.45;
  }
  .wrap { max-width: 720px; margin: 0 auto; }
  .brand { font-size: 15px; font-weight: 600; letter-spacing: -0.02em; }
  .head { display: flex; justify-content: space-between; align-items: baseline;
          gap: 12px; border-bottom: 1px solid #e6e6e6; padding-bottom: 10px; margin-top: 24px; }
  h1 { font-size: 22px; font-weight: 600; margin: 0; letter-spacing: -0.02em; }
  .meta { font-size: 11.5px; color: #6b6b6b; }
  h2 { font-size: 14px; font-weight: 600; margin: 22px 0 2px; }
  .byline { font-size: 11.5px; color: #777; margin: 0 0 4px; }
  .status { font-size: 12px; color: #444; margin: 4px 0 0; }
  .open { font-size: 12px; font-weight: 600; color: #8a5a00; margin: 4px 0 0; }
  ol { margin: 6px 0 0; padding-left: 16px; border-left: 2px solid #eee; }
  ol li { font-size: 11.5px; color: #555; margin: 1px 0; }
  .basis { font-size: 11px; font-style: italic; color: #888; margin: 4px 0 0; }
  .labs { font-size: 12px; margin: 6px 0 0; }
  .labs li { margin: 2px 0; }
  .adherence { font-size: 11px; color: #888; font-style: italic; }
  .questions { font-size: 12px; margin: 4px 0 0; padding-left: 18px; }
  .note { margin-top: 26px; border-top: 1px solid #e6e6e6; padding-top: 10px;
          font-size: 10.5px; color: #8a8a8a; }
  @media print {
    body { padding: 0; }
    .no-print { display: none; }
    h2 { break-after: avoid; }
  }
"""


def render_html(export: DoctorExport) -> str:
    generated = export.generated_at.strftime("%d %b %Y, %H:%M UTC")

    medicine_blocks: list[str] = []
    for med in export.medications:
        heading = escape(med.name)
        if med.current_dose:
            heading += f" <span class='meta'>{escape(med.current_dose)}</span>"

        byline = ""
        if med.prescribed_by:
            byline = f"Prescribed by {escape(med.prescribed_by)}"
            if med.prescribed_on:
                byline += f" on {med.prescribed_on.strftime('%d %b %Y')}"
            byline = f"<p class='byline'>{byline}</p>"

        dims = med.dimensions
        status = (
            f"Prescribed: {escape(dims['prescribed']['status'].lower())} &middot; "
            f"Patient reports: {escape(dims['reported_taking']['status'].lower())} &middot; "
            f"Stock: {escape(dims['available']['status'].lower())} &middot; "
            f"Confirmed: {escape(dims['confirmed_status']['status'].lower())}"
        )

        open_note = (
            f"<p class='open'>{med.open_cases} unresolved issue(s) on this medicine</p>"
            if med.open_cases
            else ""
        )

        timeline = ""
        if med.timeline:
            rows = "".join(
                f"<li><strong>{entry.date.strftime('%d %b %Y')}</strong> "
                f"{escape(entry.detail)} <span class='meta'>({escape(entry.source)})</span></li>"
                for entry in med.timeline[-10:]
            )
            timeline = f"<ol>{rows}</ol>"

        medicine_blocks.append(
            f"<section><h2>{heading}</h2>{byline}"
            f"<p class='status'>{status}</p>{open_note}{timeline}"
            f"<p class='basis'>{escape(med.evidence_basis)}</p></section>"
        )

    if not medicine_blocks:
        medicine_blocks.append("<p class='meta'>No medicines recorded yet.</p>")

    labs = ""
    if export.lab_findings:
        items = []
        for finding in export.lab_findings:
            line = f"<strong>{escape(finding['test_name'])}</strong>: {escape(str(finding['value']))}"
            if finding.get("unit"):
                line += f" {escape(str(finding['unit']))}"
            if finding.get("captured_on"):
                line += f" <span class='meta'>({escape(str(finding['captured_on']))})</span>"
            window = (finding.get("adherence_before") or [{}])[0]
            if window.get("reported_adhered_percent") is not None:
                line += (
                    f"<br><span class='adherence'>{escape(str(window.get('medication_name')))} "
                    f"was reported taken on {window['reported_adhered_percent']}% of recorded "
                    f"days before this test. Values are as printed, not interpreted.</span>"
                )
            items.append(f"<li>{line}</li>")
        labs = f"<h2>Lab results</h2><ul class='labs'>{''.join(items)}</ul>"

    questions = ""
    if export.questions_to_discuss:
        items = "".join(f"<li>{escape(q)}</li>" for q in export.questions_to_discuss)
        questions = f"<h2>Questions raised by the family</h2><ul class='questions'>{items}</ul>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(export.patient_name)} - Taalmel Sync</title>
  <style>{_STYLE}</style>
</head>
<body>
  <div class="wrap">
    <p class="brand">Taalmel</p>
    <div class="head">
      <h1>{escape(export.patient_name)}</h1>
      <p class="meta">{generated}</p>
    </div>
    <p class="meta">{export.unresolved_case_count} unresolved</p>
    {''.join(medicine_blocks)}
    {labs}
    {questions}
    <p class="note">{escape(export.note)}</p>
  </div>
</body>
</html>"""
