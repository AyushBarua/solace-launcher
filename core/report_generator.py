"""
ReportGenerator — creates a clinical PDF progress report from session log data.

Uses reportlab for PDF generation. Falls back gracefully if not installed.
Summary paragraph is rule-based template generation (Stage 1).

Output sections:
  1. Patient summary
  2. ROM progress table + trend
  3. Session consistency calendar
  4. Difficulty progression
  5. Pain & wellbeing log
  6. Milestones achieved
  7. Clinical summary paragraph (template-based)
"""
import os
import sys
from datetime import date, datetime
from typing import Optional

from core.session_manager import SessionManager
from core.milestone_manager import MILESTONE_MAP


def _get_output_dir() -> str:
    from core.paths import get_data_dir
    return get_data_dir()


def generate_report(sm: SessionManager, profile: dict,
                    output_path: Optional[str] = None) -> str:
    """
    Generate a PDF report for the given profile.
    Returns the path to the saved PDF file.
    Raises ImportError with a clear message if reportlab is not installed.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table,
            TableStyle, HRFlowable, PageBreak
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
    except ImportError:
        raise ImportError(
            "reportlab is required for PDF generation.\n"
            "Install it with: pip install reportlab"
        )

    # ── Data gathering ────────────────────────────────────────────────────────
    sessions     = sm.get_all_sessions()
    rom_history  = sm.get_rom_history()
    baseline     = sm.get_baseline_rom()
    milestones   = sm.get_milestones()
    streak       = sm.get_streak()
    total        = sm.get_total_sessions()
    name         = profile.get("name", "Patient")
    report_date  = date.today().strftime("%d %B %Y")

    if not output_path:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        fname = f"Solace_Report_{name.replace(' ', '_')}_{timestamp}.pdf"
        output_path = os.path.join(_get_output_dir(), fname)

    # ── Setup ─────────────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )

    W, H = A4
    styles = getSampleStyleSheet()

    # Custom styles
    GOLD   = colors.HexColor("#D2A857")
    DARK   = colors.HexColor("#0d0b09")
    GREY   = colors.HexColor("#888888")
    RED    = colors.HexColor("#C0392B")
    GREEN  = colors.HexColor("#27AE60")
    AMBER  = colors.HexColor("#F39C12")

    h1 = ParagraphStyle("H1", fontSize=28, leading=34, fontName="Helvetica-Bold",
                         textColor=DARK, spaceAfter=6)
    h2 = ParagraphStyle("H2", fontSize=16, leading=20, fontName="Helvetica-Bold",
                         textColor=GOLD, spaceAfter=12, spaceBefore=16)
    body = ParagraphStyle("Body", fontSize=11, fontName="Helvetica",
                           textColor=DARK, leading=16, spaceAfter=4)
    small = ParagraphStyle("Small", fontSize=9, fontName="Helvetica",
                            textColor=GREY, spaceAfter=2)
    bold_body = ParagraphStyle("BoldBody", fontSize=11, leading=16, fontName="Helvetica-Bold",
                                textColor=DARK, spaceAfter=4)

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("Solace", ParagraphStyle(
        "Brand", fontSize=11, fontName="Helvetica", textColor=GOLD, spaceAfter=2)))
    story.append(Paragraph("Rehabilitation Progress Report", h1))
    story.append(Spacer(1, 0.2*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceAfter=0))
    story.append(Spacer(1, 0.4*cm))

    # ── 1. Patient summary ─────────────────────────────────────────────────────
    story.append(Paragraph("Patient Summary", h2))

    period_start = sessions[0]["date"] if sessions else report_date
    period_end   = sessions[-1]["date"] if sessions else report_date
    total_time_min = sum(s.get("duration_seconds", 0) for s in sessions) // 60

    pain_count = sum(1 for s in sessions if s.get("pain_report") == "pain")

    summary_data = [
        ["Patient Name",    name],
        ["Report Generated", report_date],
        ["Report Period",   f"{period_start}  →  {period_end}"],
        ["Total Sessions",  str(total)],
        ["Total Play Time", f"{total_time_min} minutes"],
        ["Current Streak",  f"{streak} days"],
        ["Pain Reports",    str(pain_count)],
    ]
    t = Table(summary_data, colWidths=[5*cm, 10*cm])
    t.setStyle(TableStyle([
        ("FONTNAME",   (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME",   (1,0), (1,-1), "Helvetica"),
        ("FONTSIZE",   (0,0), (-1,-1), 11),
        ("TEXTCOLOR",  (0,0), (0,-1), GREY),
        ("TEXTCOLOR",  (1,0), (1,-1), DARK),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, colors.HexColor("#F8F6F2")]),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#E0DDD8")),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))

    # ── 2. ROM Progress ────────────────────────────────────────────────────────
    story.append(Paragraph("Range of Movement (ROM) Progress", h2))

    if baseline and rom_history:
        story.append(Paragraph(
            "ROM is measured daily during the warmup. Higher values = greater reach.",
            small
        ))
        story.append(Spacer(1, 0.2*cm))

        # §5: anatomical names + real DEGREES from the 'deg' block + squeeze.
        def _row(rec, date_label):
            deg = rec.get("deg") or {}
            def d(k, legacy, mx):
                if deg and k in deg:
                    return f"{deg.get(k, 0):.0f}°"
                return f"{abs(rec.get(legacy, 0)) * mx:.0f}°"   # legacy→deg
            sq = rec.get("squeeze_max")
            sq_s = f"{int(sq*100)}%" if sq is not None else "—"
            return [date_label,
                    d("flexion", "max_down", 50), d("extension", "max_up", 43),
                    d("pronation", "max_right", 63), d("supination", "max_left", 72),
                    sq_s]

        rom_table_data = [["Date", "Flexion", "Extension",
                           "Pronation", "Supination", "Squeeze"]]
        rom_table_data.append(_row(baseline, baseline.get("date", "Baseline")))
        for r in rom_history[-8:]:
            rom_table_data.append(_row(r, r["date"]))

        rom_t = Table(rom_table_data,
                      colWidths=[3*cm, 2.5*cm, 2.6*cm, 2.6*cm, 2.7*cm, 2.2*cm])
        rom_t.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,0),  DARK),
            ("TEXTCOLOR",   (0,0), (-1,0),  colors.white),
            ("FONTNAME",    (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTNAME",    (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",    (0,0), (-1,-1), 10),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F8F6F2")]),
            ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#E0DDD8")),
            ("ALIGN",       (1,0), (-1,-1), "CENTER"),
            ("TOPPADDING",  (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0), (-1,-1), 5),
        ]))
        story.append(rom_t)

        # Improvement summary — all four anatomical directions (§5 / M1)
        story.append(Spacer(1, 0.3*cm))
        for axis, label in [("right", "Pronation"), ("left", "Supination"),
                            ("up", "Extension"), ("down", "Flexion")]:
            pct = sm.get_rom_improvement_pct(axis)
            if pct is not None:
                color_str = "green" if pct >= 0 else "red"
                arrow = "▲" if pct >= 0 else "▼"
                story.append(Paragraph(
                    f"<b>{label}:</b> {arrow} {abs(pct):.1f}% from baseline",
                    ParagraphStyle("Imp", fontSize=11, textColor=GREEN if pct >= 0 else RED,
                                   fontName="Helvetica-Bold", spaceAfter=3)
                ))
    else:
        story.append(Paragraph(
            "No ROM data available yet. ROM is captured during the daily warmup.",
            body
        ))

    story.append(Spacer(1, 0.5*cm))

    # ── 3. Session Consistency ────────────────────────────────────────────────
    story.append(Paragraph("Session Consistency (Last 30 Days)", h2))

    from datetime import timedelta
    today = date.today()
    start_date = today - timedelta(days=29)
    session_dates = set(s["date"] for s in sessions)

    month_str = start_date.strftime('%B %Y')
    if start_date.month != today.month:
        month_str = f"{start_date.strftime('%B %Y')} - {today.strftime('%B %Y')}"
    
    story.append(Paragraph(f"<b>Period:</b> {month_str}", body))
    story.append(Spacer(1, 0.2*cm))

    cal_data = [["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]
    start_weekday = start_date.weekday()
    current_row = [""] * start_weekday
    
    for i in range(30):
        d = start_date + timedelta(days=i)
        day_str = d.strftime('%d')
        if i == 0 or d.day == 1:
            day_str = d.strftime('%d %b')
        current_row.append(day_str)
        if len(current_row) == 7:
            cal_data.append(current_row)
            current_row = []
            
    if current_row:
        current_row.extend([""] * (7 - len(current_row)))
        cal_data.append(current_row)
        
    cal_table = Table(cal_data, colWidths=[1.2*cm]*7)
    
    style_cmds = [
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#E0DDD8")),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F8F6F2")),
        ("TEXTCOLOR", (0,0), (-1,0), DARK),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ]
    
    row_idx = 1
    col_idx = start_weekday
    for i in range(30):
        ds = (start_date + timedelta(days=i)).isoformat()
        if ds in session_dates:
            style_cmds.append(("BACKGROUND", (col_idx, row_idx), (col_idx, row_idx), GREEN))
            style_cmds.append(("TEXTCOLOR", (col_idx, row_idx), (col_idx, row_idx), colors.white))
            style_cmds.append(("FONTNAME", (col_idx, row_idx), (col_idx, row_idx), "Helvetica-Bold"))
        else:
            style_cmds.append(("BACKGROUND", (col_idx, row_idx), (col_idx, row_idx), colors.white))
            style_cmds.append(("TEXTCOLOR", (col_idx, row_idx), (col_idx, row_idx), GREY))
            
        col_idx += 1
        if col_idx > 6:
            col_idx = 0
            row_idx += 1

    cal_table.setStyle(TableStyle(style_cmds))
    story.append(cal_table)
    story.append(Spacer(1, 0.2*cm))
    
    legend_data = [["", "Session Played", "", "No Session"]]
    lt = Table(legend_data, colWidths=[0.5*cm, 2.5*cm, 0.5*cm, 2.5*cm])
    lt.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,0), GREEN),
        ("BACKGROUND", (2,0), (2,0), colors.white),
        ("GRID", (2,0), (2,0), 0.5, colors.HexColor("#E0DDD8")),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("TEXTCOLOR", (0,0), (-1,-1), GREY),
    ]))
    story.append(lt)
    story.append(Spacer(1, 0.3*cm))

    active_days = len([s["date"] for s in sessions if s["date"] >= start_date.isoformat()])
    story.append(Paragraph(f"Active days in last 30 days: <b>{active_days}</b>", body))
    story.append(Spacer(1, 0.5*cm))

    # ── 4. Difficulty progression ─────────────────────────────────────────────
    story.append(Paragraph("Difficulty Progression", h2))
    if sessions:
        diff_data = [["Date", "Game", "Difficulty"]]
        # Show sessions where difficulty changed
        prev_diff = None
        for s in sessions:
            d = s.get("difficulty", 0.25)
            if d != prev_diff:
                diff_data.append([
                    s["date"], s.get("game_id", "-"),
                    f"{d:.2f}×"
                ])
                prev_diff = d
        if len(diff_data) > 1:
            dt = Table(diff_data, colWidths=[4*cm, 7*cm, 4*cm])
            dt.setStyle(TableStyle([
                ("BACKGROUND",  (0,0), (-1,0),  DARK),
                ("TEXTCOLOR",   (0,0), (-1,0),  colors.white),
                ("FONTNAME",    (0,0), (-1,0),  "Helvetica-Bold"),
                ("FONTNAME",    (0,1), (-1,-1), "Helvetica"),
                ("FONTSIZE",    (0,0), (-1,-1), 10),
                ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#E0DDD8")),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F8F6F2")]),
                ("TOPPADDING",  (0,0), (-1,-1), 5),
                ("BOTTOMPADDING",(0,0), (-1,-1), 5),
            ]))
            story.append(dt)
        else:
            story.append(Paragraph("Difficulty has remained constant so far.", body))
    else:
        story.append(Paragraph("No sessions recorded yet.", body))
    story.append(Spacer(1, 0.5*cm))

    # ── 5. Pain & wellbeing log ───────────────────────────────────────────────
    story.append(Paragraph("Pain & Wellbeing Log", h2))
    pain_sessions = [s for s in sessions if s.get("pain_report") in ("pain", "tired")]
    if pain_sessions:
        pain_data = [["Date", "Game", "Report"]]
        for s in pain_sessions:
            report = s.get("pain_report", "")
            pain_data.append([
                s["date"],
                s.get("game_id", "-"),
                "Pain reported" if report == "pain" else "Tired"
            ])
        pt = Table(pain_data, colWidths=[4*cm, 7*cm, 5*cm])
        pt.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,0),  DARK),
            ("TEXTCOLOR",   (0,0), (-1,0),  colors.white),
            ("FONTNAME",    (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTNAME",    (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",    (0,0), (-1,-1), 10),
            ("GRID",        (0,0), (-1,-1), 0.5, colors.HexColor("#E0DDD8")),
            ("TEXTCOLOR",   (2,1), (2,-1),  RED),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FFF5F5")]),
            ("TOPPADDING",  (0,0), (-1,-1), 5),
            ("BOTTOMPADDING",(0,0), (-1,-1), 5),
        ]))
        story.append(pt)
    else:
        story.append(Paragraph(
            "No pain or discomfort reported. Excellent!",
            ParagraphStyle("Good", fontSize=11, textColor=GREEN,
                           fontName="Helvetica-Bold", spaceAfter=4)
        ))
    story.append(Spacer(1, 0.5*cm))

    # ── 6. Milestones ─────────────────────────────────────────────────────────
    story.append(Paragraph("Milestones Achieved", h2))
    if milestones:
        for mid in milestones:
            m = MILESTONE_MAP.get(mid)
            if m:
                story.append(Paragraph(
                    f"{m['emoji']}  <b>{m['title']}</b> — {m['desc']}", body
                ))
    else:
        story.append(Paragraph("No milestones yet — keep going!", body))
    story.append(Spacer(1, 0.5*cm))

    # ── 7. Clinical summary paragraph (template-based) ────────────────────────
    story.append(Paragraph("Clinical Summary", h2))
    story.append(Spacer(1, 0.1*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY, spaceAfter=0))
    story.append(Spacer(1, 0.4*cm))

    summary = _build_summary(name, sessions, sm, pain_count, streak)
    story.append(Paragraph(summary, body))

    story.append(Spacer(1, 1*cm))
    story.append(Paragraph(
        f"Report generated by Solace  ·  {report_date}  ·  Data stored locally on patient device.",
        ParagraphStyle("Footer", fontSize=8, textColor=GREY, fontName="Helvetica",
                       alignment=TA_CENTER)
    ))

    # ── Build PDF ──────────────────────────────────────────────────────────────
    doc.build(story)
    return output_path


def _build_summary(name: str, sessions: list, sm: SessionManager,
                   pain_count: int, streak: int) -> str:
    """Builds a readable clinical summary paragraph from structured data."""
    total = len(sessions)
    if total == 0:
        return f"{name} has not yet completed any sessions."

    # Period
    period_days = 1
    if total >= 2:
        try:
            d1 = date.fromisoformat(sessions[0]["date"])
            d2 = date.fromisoformat(sessions[-1]["date"])
            period_days = max(1, (d2 - d1).days)
        except Exception:
            pass

    weeks = max(1, period_days // 7)
    total_min = sum(s.get("duration_seconds", 0) for s in sessions) // 60

    # ROM trend — M1 fix: all four anatomical directions, not just right/up
    _DIR_NAMES = {"right": "pronation", "left": "supination",
                  "down": "flexion",   "up": "extension"}
    imps = {name: sm.get_rom_improvement_pct(axis)
            for axis, name in _DIR_NAMES.items()}
    known = {k: v for k, v in imps.items() if v is not None}

    rom_sentence = ""
    if known:
        best_dir  = max(known, key=known.get)
        worst_dir = min(known, key=known.get)
        if all(v >= 0 for v in known.values()):
            parts = ", ".join(f"{k} {v:+.1f}%" for k, v in known.items())
            rom_sentence = (
                f"Range of movement has improved from baseline across the "
                f"measured directions ({parts}). "
            )
        else:
            rom_sentence = (
                f"{known[best_dir]:+.1f}% change in {best_dir} leads the progress "
                f"from baseline, while {worst_dir} shows the slowest trend "
                f"({known[worst_dir]:+.1f}%) and may benefit from targeted "
                f"exercises. "
            )

    # Pain
    pain_sentence = ""
    if pain_count == 0:
        pain_sentence = "No pain or discomfort was reported throughout the programme. "
    elif pain_count <= 2:
        pain_sentence = f"Discomfort was reported on {pain_count} occasion(s). Monitoring recommended. "
    else:
        pain_sentence = (
            f"Pain or discomfort was reported on {pain_count} occasions. "
            f"Clinical review of exercise intensity is recommended. "
        )

    # Consistency
    adherence_pct = int((total / max(period_days, 1)) * 100)
    if streak >= 7:
        consistency = f"Patient demonstrated excellent consistency with a {streak}-day streak. "
    elif adherence_pct >= 60:
        consistency = "Patient showed good adherence to the therapy schedule. "
    else:
        consistency = "Session frequency has been lower than ideal. Motivational support may help. "

    summary = (
        f"{name} completed {total} sessions over approximately {weeks} week(s), "
        f"totalling {total_min} minutes of active therapy. "
        f"{consistency}"
        f"{rom_sentence}"
        f"{pain_sentence}"
        f"Current streak: {streak} consecutive day(s)."
    )
    return summary
