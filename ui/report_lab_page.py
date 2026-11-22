"""
ReportLabPage — dedicated report generation hub.

Lets the therapist or patient generate a clinical PDF summary
of the session history, ROM progress, pain log, and milestones.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from core.theme import (
    FONT_DISPLAY, FONT_BODY, ON_SURFACE, ON_SURFACE_VAR,
    PRIMARY_CONTAINER, SURFACE_CON_LOW, OUTLINE_VARIANT,
    SURFACE_DIM, BACKGROUND
)

_CARD   = SURFACE_CON_LOW
_BORDER = OUTLINE_VARIANT
_GOLD   = PRIMARY_CONTAINER
_GOLD_L = "rgba(242,202,80,0.90)"
_GOLD_D = "rgba(210,168,87,1.00)"
_TEXT   = ON_SURFACE
_TEXT2  = ON_SURFACE_VAR
_MUTED  = "rgba(255,255,255,0.35)"
_INNER  = SURFACE_DIM


# ── Background PDF thread ─────────────────────────────────────────────────────

class _PDFThread(QThread):
    done  = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, sm, profile, path, parent=None):
        super().__init__(parent)
        self._sm      = sm
        self._profile = profile
        self._path    = path

    def run(self):
        try:
            from core.report_generator import generate_report
            out = generate_report(self._sm, self._profile, self._path)
            self.done.emit(out)
        except Exception as e:
            self.error.emit(str(e))


# ── Stat summary chip ─────────────────────────────────────────────────────────

def _stat_chip(label: str, value: str) -> QFrame:
    chip = QFrame()
    chip.setStyleSheet(
        f"QFrame {{ background:{_INNER}; border-radius:14px; border:1px solid {_BORDER}; }}"
    )
    cl = QVBoxLayout(chip)
    cl.setContentsMargins(20, 14, 20, 14)
    cl.setSpacing(4)
    val_lbl = QLabel(value)
    val_lbl.setStyleSheet(
        f"color:{_GOLD}; font-family:'{FONT_DISPLAY}'; font-size:36px; "
        f"font-weight:800; background:transparent;"
    )
    val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_lbl = QLabel(label.upper())
    lbl_lbl.setStyleSheet(
        f"color:{_TEXT2}; font-family:'{FONT_DISPLAY}'; font-size:11px; "
        f"font-weight:700; letter-spacing:1.5px; background:transparent;"
    )
    lbl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cl.addWidget(val_lbl)
    cl.addWidget(lbl_lbl)
    return chip


# ── Page ──────────────────────────────────────────────────────────────────────

class ReportLabPage(QScrollArea):
    """Dedicated page for generating clinical PDF reports."""

    def __init__(self, session_manager, profile: dict, parent=None):
        super().__init__(parent)
        self._sm      = session_manager
        self._profile = profile
        self._pdf_thread: _PDFThread | None = None

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(52, 36, 52, 120)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        title = QLabel("Report Lab")
        title.setStyleSheet(
            f"color:{ON_SURFACE}; font-family:'{FONT_DISPLAY}';"
            f"font-size:52px; font-weight:800; letter-spacing:-0.02em; background:transparent;"
        )
        sub = QLabel("Generate a clinical PDF your therapist or doctor can review.")
        sub.setStyleSheet(
            f"color:{ON_SURFACE_VAR}; font-family:'{FONT_BODY}';"
            f"font-size:16px; background:transparent;"
        )
        root.addWidget(title)
        root.addSpacing(6)
        root.addWidget(sub)
        root.addSpacing(36)

        # ── Snapshot chips ────────────────────────────────────────────────────
        snap_row = QHBoxLayout()
        snap_row.setSpacing(12)

        total   = self._sm.get_total_sessions()
        streak  = self._sm.get_streak()
        mins    = self._sm.get_today_duration_seconds() // 60
        n_miles = len(self._sm.get_milestones())

        self._chips = []
        for label, val in [
            ("Sessions",   str(total)),
            ("Day Streak", str(streak)),
            ("Min Today",  f"{mins}m"),
            ("Milestones", str(n_miles)),
        ]:
            chip = _stat_chip(label, val)
            snap_row.addWidget(chip, stretch=1)
            self._chips.append(chip)

        root.addLayout(snap_row)
        root.addSpacing(32)

        # ── What's included card ──────────────────────────────────────────────
        info_card = QFrame()
        info_card.setStyleSheet(
            f"QFrame {{ background:{_CARD}; border-radius:18px; border:1px solid {_BORDER}; }}"
        )
        il = QVBoxLayout(info_card)
        il.setContentsMargins(28, 24, 28, 24)
        il.setSpacing(16)

        info_title = QLabel("What's included in the report")
        info_title.setStyleSheet(
            f"color:{_TEXT}; font-family:'{FONT_DISPLAY}'; font-size:20px; "
            f"font-weight:700; background:transparent;"
        )
        il.addWidget(info_title)

        sections = [
            ("\U0001f4ca", "ROM Progress",       "Range-of-motion over time vs your baseline."),
            ("\U0001f4c5", "Session Calendar",    "30-day activity heatmap showing consistency."),
            ("\U0001f3af", "Difficulty Trend",    "How game difficulty has progressed each session."),
            ("\U0001f49c", "Pain & Wellbeing Log","Post-session pain reports across the period."),
            ("\U0001f3c6", "Milestones Earned",   "Every achievement unlocked so far."),
            ("\U0001f4dd", "Clinical Summary",    "Auto-generated paragraph with key observations."),
        ]
        grid = QHBoxLayout()
        grid.setSpacing(16)
        left_col = QVBoxLayout(); left_col.setSpacing(10)
        right_col = QVBoxLayout(); right_col.setSpacing(10)
        for i, (emoji, name, desc) in enumerate(sections):
            row = QHBoxLayout(); row.setSpacing(12)
            em = QLabel(emoji)
            em.setStyleSheet("font-size:20px; background:transparent;")
            em.setFixedWidth(28)
            txt = QVBoxLayout(); txt.setSpacing(1)
            n_lbl = QLabel(name)
            n_lbl.setStyleSheet(
                f"color:{_TEXT}; font-family:'{FONT_DISPLAY}'; font-size:14px; "
                f"font-weight:700; background:transparent;"
            )
            d_lbl = QLabel(desc)
            d_lbl.setStyleSheet(
                f"color:{_TEXT2}; font-family:'{FONT_BODY}'; font-size:12px; background:transparent;"
            )
            txt.addWidget(n_lbl)
            txt.addWidget(d_lbl)
            row.addWidget(em)
            row.addLayout(txt)
            row.addStretch()
            w = QWidget(); w.setStyleSheet("background:transparent;")
            w.setLayout(row)
            (left_col if i % 2 == 0 else right_col).addWidget(w)
        grid.addLayout(left_col)
        grid.addLayout(right_col)
        il.addLayout(grid)
        root.addWidget(info_card)
        root.addSpacing(24)

        # ── Generate card ─────────────────────────────────────────────────────
        gen_card = QFrame()
        gen_card.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #1e1a0e, stop:1 #141208);"
            f"border:1px solid rgba(242,202,80,0.18); border-radius:18px; }}"
        )
        gl = QVBoxLayout(gen_card)
        gl.setContentsMargins(28, 24, 28, 24)
        gl.setSpacing(14)

        gen_title = QLabel("\U0001f4c4  Generate PDF Report")
        gen_title.setStyleSheet(
            f"color:{_GOLD}; font-family:'{FONT_DISPLAY}'; font-size:22px; "
            f"font-weight:800; background:transparent;"
        )
        gen_desc = QLabel(
            f"A report for <b>{self._profile.get('name', 'Patient')}</b> will be saved as a PDF "
            "you can share directly with your therapist or doctor."
        )
        gen_desc.setStyleSheet(
            f"color:{_TEXT2}; font-family:'{FONT_BODY}'; font-size:14px; background:transparent;"
        )
        gen_desc.setWordWrap(True)

        self._gen_btn = QPushButton("\U0001f4e5  Save PDF Report")
        self._gen_btn.setFixedHeight(54)
        self._gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gen_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {_GOLD_L}, stop:1 {_GOLD_D});
                color: #3c2f00;
                border: none;
                border-radius: 10px;
                font-family: '{FONT_DISPLAY}';
                font-size: 15px;
                font-weight: 800;
            }}
            QPushButton:hover {{ background: {_GOLD}; }}
            QPushButton:disabled {{ background:{_INNER}; color:{_MUTED}; }}
        """)
        self._gen_btn.clicked.connect(self._generate)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color:{_MUTED}; font-family:'{FONT_BODY}'; font-size:13px; background:transparent;"
        )

        gl.addWidget(gen_title)
        gl.addWidget(gen_desc)
        gl.addWidget(self._gen_btn)
        gl.addWidget(self._status_lbl)

        root.addWidget(gen_card)
        root.addStretch()

    # ── Generate handler ──────────────────────────────────────────────────────

    def _generate(self):
        from datetime import datetime as _dt
        name    = self._profile.get("name", "User").replace(" ", "_")
        ts      = _dt.now().strftime("%Y-%m-%d_%H-%M")
        default = f"Solace_Report_{name}_{ts}.pdf"
        path, _ = QFileDialog.getSaveFileName(None, "Save Report", default, "PDF Files (*.pdf)")
        self.window().update()
        if not path:
            return
        self._gen_btn.setEnabled(False)
        self._gen_btn.setText("  Generating…")
        self._status_lbl.setText("Building your report, please wait…")
        self._pdf_thread = _PDFThread(self._sm, self._profile, path)
        self._pdf_thread.done.connect(self._on_done)
        self._pdf_thread.error.connect(self._on_error)
        self._pdf_thread.start()

    def _on_done(self, path: str):
        self._gen_btn.setEnabled(True)
        self._gen_btn.setText("\U0001f4e5  Save PDF Report")
        self._status_lbl.setText(f"✅ Saved to: {path}")

    def _on_error(self, msg: str):
        self._gen_btn.setEnabled(True)
        self._gen_btn.setText("\U0001f4e5  Save PDF Report")
        self._status_lbl.setText(f"❌ {msg}")

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        """Called after a session ends to update the snapshot chips."""
        total   = self._sm.get_total_sessions()
        streak  = self._sm.get_streak()
        mins    = self._sm.get_today_duration_seconds() // 60
        n_miles = len(self._sm.get_milestones())
        values  = [str(total), str(streak), f"{mins}m", str(n_miles)]
        for chip, val in zip(self._chips, values):
            lbl = chip.findChild(QLabel)
            if lbl:
                lbl.setText(val)

    def refresh_theme(self):
        pass
