"""Корпоративное оформление: тёмно-синий, белый, серый."""

NAVY = "#1F3A5F"
NAVY_DARK = "#152A45"
NAVY_LIGHT = "#2E5283"
BG = "#F3F5F8"
CARD = "#FFFFFF"
LINE = "#D9DFE7"
TEXT = "#1B2430"
MUTED = "#66717F"
OK = "#1E7B4F"
BAD = "#B3362F"
WARN = "#A0640A"

STATUS_COLORS = {
    "approved": OK, "passed": OK, "active": OK, "unchanged": MUTED,
    "review": WARN, "draft": MUTED, "revision_review": WARN, "pending_update": WARN, "modified": WARN, "manual": WARN,
    "retest": WARN,
    "rejected": BAD, "failed": BAD, "obsolete": MUTED, "archived": MUTED, "revoked": BAD, "removed": BAD,
    "not_tested": MUTED, "added": NAVY_LIGHT, "superseded": MUTED,
}

QSS = f"""
* {{ font-family: "Segoe UI", "Arial"; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#Sidebar {{ background: {NAVY}; }}
QWidget#Sidebar QPushButton {{
    color: #DCE4EE; background: transparent; border: none; text-align: left;
    padding: 9px 18px; font-size: 10pt; border-left: 3px solid transparent;
}}
QWidget#Sidebar QPushButton:hover {{ background: {NAVY_LIGHT}; color: white; }}
QWidget#Sidebar QPushButton:checked {{ background: {NAVY_DARK}; color: white; border-left: 3px solid #8FB3E8; font-weight: 600; }}
QLabel#AppTitle {{ color: white; font-size: 14pt; font-weight: 700; padding: 18px 18px 4px 18px; }}
QLabel#AppSubtitle {{ color: #A9B8CB; font-size: 8.5pt; padding: 0 18px 14px 18px; }}
QWidget#TopBar {{ background: {CARD}; border-bottom: 1px solid {LINE}; }}
QLabel#PageTitle {{ font-size: 15pt; font-weight: 600; color: {NAVY}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#H2 {{ font-size: 11.5pt; font-weight: 600; color: {NAVY}; }}
QFrame#Card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 8px; }}
QLabel#StatValue {{ font-size: 20pt; font-weight: 700; color: {NAVY}; }}
QLabel#StatLabel {{ color: {MUTED}; font-size: 9pt; }}
QPushButton {{
    background: {CARD}; border: 1px solid #B9C3D0; border-radius: 6px; padding: 6px 14px; min-height: 18px;
}}
QPushButton:hover {{ border-color: {NAVY_LIGHT}; }}
QPushButton:disabled {{ color: #9AA4B1; border-color: {LINE}; }}
QPushButton[primary="true"] {{ background: {NAVY}; color: white; border-color: {NAVY}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {NAVY_LIGHT}; }}
QPushButton[primary="true"]:disabled {{ background: #8EA0B8; border-color: #8EA0B8; color: #EEF2F6; }}
QPushButton[danger="true"] {{ color: {BAD}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: white; border: 1px solid #C3CCD8; border-radius: 5px; padding: 5px 7px;
    selection-background-color: {NAVY_LIGHT}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus {{
    border: 1px solid {NAVY_LIGHT};
}}
QTableView, QTableWidget, QListWidget, QTreeWidget {{
    background: white; border: 1px solid {LINE}; border-radius: 6px; gridline-color: #EDF0F4;
    selection-background-color: #DCE7F7; selection-color: {TEXT}; alternate-background-color: #F8FAFC;
}}
QHeaderView::section {{
    background: #E9EEF4; color: {NAVY}; font-weight: 600; border: none; border-right: 1px solid {LINE};
    border-bottom: 1px solid {LINE}; padding: 6px;
}}
QTabWidget::pane {{ border: 1px solid {LINE}; background: white; border-radius: 6px; }}
QTabBar::tab {{ background: #E6EBF1; padding: 7px 14px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: white; color: {NAVY}; font-weight: 600; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 6px; margin-top: 14px; background: white; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {NAVY}; font-weight: 600; }}
QProgressBar {{ border: 1px solid {LINE}; border-radius: 5px; background: white; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {NAVY_LIGHT}; border-radius: 4px; }}
QRadioButton, QCheckBox {{ spacing: 8px; }}
QFrame#Option {{ background: white; border: 1px solid #C3CCD8; border-radius: 8px; }}
QFrame#Option[selected="true"] {{ border: 2px solid {NAVY_LIGHT}; background: #EEF4FD; }}
QLabel#QuestionText {{ font-size: 14pt; font-weight: 600; color: {TEXT}; }}
QLabel#Timer {{ font-size: 13pt; font-weight: 700; color: {NAVY}; }}
QToolTip {{ background: {NAVY}; color: white; border: none; padding: 5px; }}
"""
