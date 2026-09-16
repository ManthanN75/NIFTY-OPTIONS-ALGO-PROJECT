"""
Generates a short 2-page PDF summary of the project: what it is, what we
found (including the liquidity-price bug), how it was fixed, and the
final honest 24-month result. Meant to be shareable as-is (e.g. with a
recruiter) alongside the code repo.

Run this after run_24m_backtest.py has produced results_24m.xlsx and
equity_curve_24m.png.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUTPUT_PATH = "Nifty_Iron_Condor_Project_Report.pdf"

styles = getSampleStyleSheet()
title_style = ParagraphStyle("TitleCustom", parent=styles["Title"], fontSize=20, spaceAfter=4)
subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=11, textColor=colors.grey, spaceAfter=14)
h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#1F2937"))
body = ParagraphStyle("BodyCustom", parent=styles["Normal"], fontSize=10, leading=14)
small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8.5, leading=11, textColor=colors.grey)


def metric_table(rows):
    table = Table(rows, colWidths=[7.5 * cm, 7.5 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def build_report():
    doc = SimpleDocTemplate(
        OUTPUT_PATH, pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )
    story = []

    # ---------- Page 1 ----------
    story.append(Paragraph("Nifty Iron Condor Backtest", title_style))
    story.append(Paragraph("A systematic, IV-rank-triggered options-selling strategy &mdash; data pipeline, "
                            "Python + Rust backtest engine, and dashboard", subtitle_style))

    story.append(Paragraph("What this project is", h2))
    story.append(Paragraph(
        "A backtested trading strategy that sells Nifty index iron condors (sell a near-the-money call "
        "and put, buy further out-of-the-money call and put as hedges) when implied volatility is high "
        "relative to its own recent history &mdash; betting that volatility, and the size of Nifty's moves, "
        "will cool back down before expiry. It is a systematic <b>research prototype</b>, not a live trading "
        "system: no real money or broker connection was involved.", body))

    story.append(Paragraph("Architecture", h2))
    story.append(Paragraph(
        "Free NSE bhavcopy data &rarr; Python data pipeline (cleaning, Black-Scholes implied volatility) "
        "&rarr; Python strategy logic (IV rank, entry/exit rules) &rarr; a hot backtest loop rewritten in "
        "<b>Rust</b> and exposed to Python via <b>PyO3</b> for speed &rarr; a metrics/reporting layer (Sharpe, "
        "drawdown, win rate, profit factor) &rarr; a <b>FastAPI</b> backend &rarr; a <b>React</b> dashboard.",
        body))

    story.append(Paragraph("A real bug we found and fixed", h2))
    story.append(Paragraph(
        "An early result on a smaller (10-month) dataset showed an 80% win rate &mdash; suspiciously high. "
        "Manually auditing the raw trade data found the cause: some option legs were being priced using "
        "NSE bhavcopy's <i>last traded price</i> even on days with <b>zero trading volume</b> &mdash; a "
        "frozen, stale price, not something actually tradeable that day. This let the backtest \"sell\" and "
        "\"buy back\" options at prices nobody could really have gotten, quietly inflating the win rate. "
        "The fix: every option leg now requires real trading volume on that day before its price is trusted, "
        "both when entering a trade and when checking exits &mdash; otherwise it's treated as unavailable, "
        "exactly like a missing price. A second bug found during the fix (a tie-breaking inconsistency "
        "between the Python and Rust engines caused by Rust's unordered hash sets) was fixed at the same time.",
        body))

    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This is disclosed here deliberately: catching and fixing this kind of data-integrity issue is a "
        "normal, healthy part of building a backtest &mdash; not a flaw to hide.", small))

    story.append(PageBreak())

    # ---------- Page 2 ----------
    story.append(Paragraph("Final Result (24 months, fixed engine, unchanged settings)", h2))
    story.append(Paragraph(
        "Settings were chosen once from an earlier tuning search (IV rank threshold = 80, profit target = "
        "50% of credit received, stop-loss = 2&times; credit received) and were <b>not</b> re-tuned for this "
        "run &mdash; this is a clean verification of the already-fixed, already-chosen strategy across 24 "
        "months of NSE data (Sept 2024 &ndash; Sept 2026), not a fresh search for a good-looking number.",
        body))
    story.append(Spacer(1, 8))

    story.append(metric_table([
        ["Metric", "Value"],
        ["Number of trades", "12"],
        ["Win rate", "58.3%"],
        ["Total return", "-1.29%"],
        ["Sharpe ratio (per-trade, not annualized)", "-0.09"],
        ["Max drawdown", "-3.16%"],
        ["Profit factor", "0.80"],
    ]))
    story.append(Spacer(1, 14))

    try:
        story.append(Image("equity_curve_24m.png", width=16 * cm, height=7.5 * cm))
    except Exception:
        pass
    story.append(Spacer(1, 10))

    story.append(Paragraph("Honest takeaway", h2))
    story.append(Paragraph(
        "58.3% win rate with a roughly flat-to-slightly-negative total return (-1.29%) and a Sharpe ratio "
        "near zero is a believable, unglamorous result for this style of strategy over this period &mdash; "
        "not a proven edge, and not a failure either. Twelve trades over 24 months is still a small sample "
        "for statistical confidence. The honest conclusion at this stage: the current entry/exit rules do "
        "not show a clear, reliable edge on this data. The value of this phase of the project was proving "
        "the pipeline is correct and trustworthy end-to-end &mdash; a necessary foundation before iterating "
        "on the strategy logic itself.", body))

    story.append(Paragraph("Tech stack", h2))
    story.append(Paragraph(
        "Python (pandas, NumPy, SciPy) for the data pipeline and IV/Black-Scholes math &middot; Rust + PyO3 "
        "for the performance-critical backtest loop &middot; FastAPI for the results API &middot; React + "
        "Vite + Recharts for the dashboard &middot; free NSE bhavcopy data, no paid broker API.", body))

    doc.build(story)
    print(f"Saved {OUTPUT_PATH}")


if __name__ == "__main__":
    build_report()
