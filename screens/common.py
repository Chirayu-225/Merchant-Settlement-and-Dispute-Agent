"""Look and feel, number formats, and the three figure labels shared by every tab.

Every figure in the app is one of:
  Measured       computed by running the code (shows the mode that ran, and the date)
  Assumption     a choice or input written down in product/assumptions.py, with its source
  Needs testing  nothing honest can be said yet, so no number is shown
"""
from html import escape

import streamlit as st

import evaluate

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input, select, textarea {
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
.block-container { padding-top: 3.4rem; padding-bottom: 3rem; max-width: 1180px; }
h1, h2, h3 { letter-spacing: -0.01em; }
[data-testid="stSidebar"] { border-right: 1px solid #E3E8F0; }
[data-testid="stSidebar"] h3 { font-size: 0.78rem; text-transform: uppercase;
  letter-spacing: 0.06em; color: #5B6B82; }

/* top bar */
.topbar { display: flex; align-items: center; justify-content: space-between;
  background: linear-gradient(100deg, #0A2A5E 0%, #0B5FD9 100%); color: #fff;
  border-radius: 14px; padding: 18px 24px; margin-bottom: 14px; }
.topbar .name { font-size: 1.35rem; font-weight: 700; letter-spacing: -0.01em; }
.topbar .sub { font-size: 0.9rem; opacity: 0.85; margin-top: 2px; }
.topbar .badge { background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.3);
  border-radius: 999px; padding: 5px 12px; font-size: 0.78rem; white-space: nowrap; }

/* intro strip */
.intro { background: #fff; border: 1px solid #E3E8F0; border-radius: 12px;
  padding: 14px 18px; margin-bottom: 10px; color: #33445C; font-size: 0.93rem; line-height: 1.5; }
.intro b { color: #0F1B2D; }

/* cards */
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px; margin: 6px 0 4px 0; }
.kpi { background: #fff; border: 1px solid #E3E8F0; border-radius: 12px; padding: 14px 16px; }
.kpi .label { font-size: 0.8rem; color: #5B6B82; font-weight: 500; }
.kpi .value { font-size: 1.55rem; font-weight: 700; color: #0F1B2D; margin-top: 4px;
  font-variant-numeric: tabular-nums; }
.kpi .note { font-size: 0.78rem; color: #6B7A90; margin-top: 4px; line-height: 1.35; }
.kpi.good .value { color: #0E7A4B; }
.kpi.warn .value { color: #B45309; }
.kpi.bad .value { color: #C0262D; }

.card { background: #fff; border: 1px solid #E3E8F0; border-radius: 12px;
  padding: 16px 18px; margin: 8px 0; font-size: 0.9rem; color: #22324A; line-height: 1.5; }
.card h4 { margin: 0 0 8px 0; font-size: 0.95rem; color: #0F1B2D; }
.section { font-size: 1.05rem; font-weight: 650; color: #0F1B2D; margin: 22px 0 4px 0; }
.muted { color: #6B7A90; font-size: 0.85rem; }

/* verdict banners */
.verdict { border-radius: 12px; padding: 14px 18px; margin: 10px 0; font-size: 0.98rem;
  border: 1px solid; line-height: 1.45; }
.verdict .big { font-weight: 700; font-size: 1.08rem; display: block; margin-bottom: 2px; }
.verdict.good { background: #ECFDF3; border-color: #A6E9C5; color: #0B5E3A; }
.verdict.warn { background: #FFF8EB; border-color: #F7D59B; color: #7A4A06; }
.verdict.bad  { background: #FEF1F1; border-color: #F5B5B8; color: #8E1D22; }
.verdict.info { background: #EEF4FF; border-color: #B9CFF7; color: #163D7A; }

/* money breakdown */
.ledger { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.ledger td { padding: 7px 4px; border-bottom: 1px solid #EEF1F6; font-size: 0.92rem; }
.ledger td.amt { text-align: right; white-space: nowrap; }
.ledger tr.minus td { color: #5B6B82; }
.ledger tr.total td { font-weight: 700; color: #0F1B2D; border-bottom: none;
  border-top: 2px solid #D5DCE7; }
.ledger .ref { color: #8A97AB; font-size: 0.76rem; margin-left: 6px; }

/* pills and checks */
.pill { display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: 0.76rem;
  font-weight: 600; border: 1px solid; }
.pill.good { background: #ECFDF3; color: #0B5E3A; border-color: #A6E9C5; }
.pill.warn { background: #FFF8EB; color: #7A4A06; border-color: #F7D59B; }
.pill.bad  { background: #FEF1F1; color: #8E1D22; border-color: #F5B5B8; }
.pill.grey { background: #F1F4F8; color: #4A5A70; border-color: #DCE3EC; }
.check { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid #EEF1F6; }
.check:last-child { border-bottom: none; }
.check .icon { width: 20px; height: 20px; border-radius: 50%; flex: none; text-align: center;
  line-height: 20px; font-size: 0.75rem; font-weight: 700; color: #fff; margin-top: 1px; }
.check .icon.pass { background: #12A15F; }
.check .icon.fail { background: #D63B41; }
.check .icon.skip { background: #A9B4C4; }
.check .t { font-weight: 600; font-size: 0.9rem; color: #0F1B2D; }
.check .d { font-size: 0.82rem; color: #5B6B82; }

/* figure labels */
.tagline { font-size: 0.78rem; color: #6B7A90; margin: 4px 0; line-height: 1.5; }
.tag { display: inline-block; border-radius: 4px; padding: 0 6px; font-size: 0.7rem;
  font-weight: 700; letter-spacing: 0.02em; margin-right: 6px; border: 1px solid; }
.tag.measured { background: #ECFDF3; color: #0B5E3A; border-color: #A6E9C5; }
.tag.assumption { background: #FFF8EB; color: #7A4A06; border-color: #F7D59B; }
.tag.needs { background: #FEF1F1; color: #8E1D22; border-color: #F5B5B8; }

.stTabs [data-baseweb="tab"]:focus:not(:focus-visible) { outline: none; box-shadow: none; }
.stTabs [data-baseweb="tab-highlight"] { background-color: #0B5FD9; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid #E3E8F0; }
.stTabs [data-baseweb="tab"] { padding: 8px 14px; font-weight: 600; }
.footer { color: #8A97AB; font-size: 0.78rem; margin-top: 28px; padding-top: 12px;
  border-top: 1px solid #E3E8F0; }
</style>
"""

# Dispute reason codes and statuses, in words.
REASONS = {"GNR": "Goods not received", "UNAUTH": "Unauthorised payment"}
STATUS = {"PENDING": ("Not processed", "grey"), "ESCALATED": ("Needs a person", "warn"),
          "AUTO_SUBMITTED": ("Agent replied", "good"), "DRY_RUN_READY": ("Agent replied", "good")}


def style() -> None:
    st.html(CSS)


def html(text: str) -> None:
    st.html(text)


def rs(value: float | None, paise: bool = True) -> str:
    if value is None:
        return "–"
    return f"₹{value:,.2f}" if paise else f"₹{value:,.0f}"


def pct(value) -> str:
    return "–" if value is None else f"{value * 100:.1f}%"


def kpis(items: list[tuple]) -> None:
    """items: (label, value, note, tone) with tone in '', good, warn, bad."""
    cards = "".join(
        f'<div class="kpi {tone}"><div class="label">{escape(label)}</div>'
        f'<div class="value">{escape(str(value))}</div>'
        + (f'<div class="note">{escape(note)}</div>' if note else "") + "</div>"
        for label, value, note, tone in items)
    st.html(f'<div class="kpis">{cards}</div>')


def verdict(tone: str, headline: str, body: str = "") -> None:
    st.html(f'<div class="verdict {tone}"><span class="big">{escape(headline)}</span>'
            f'{escape(body)}</div>')


def section(title: str, note: str = "") -> None:
    st.html(f'<div class="section">{escape(title)}</div>'
            + (f'<div class="muted">{escape(note)}</div>' if note else ""))


def pill(text: str, tone: str) -> str:
    return f'<span class="pill {tone}">{escape(text)}</span>'


def _tag(kind: str, word: str, text: str) -> None:
    st.html(f'<div class="tagline"><span class="tag {kind}">{word}</span>{escape(text)}</div>')


def measured(note: str = "") -> None:
    _tag("measured", "MEASURED", evaluate.stamp_text() + (f" · {note}" if note else ""))


def assumption(text: str) -> None:
    _tag("assumption", "ASSUMPTION", text)


def needs_testing(text: str) -> None:
    _tag("needs", "NEEDS TESTING", text + " No number is shown.")
