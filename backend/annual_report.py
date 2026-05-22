"""Annual portfolio PDF — year-in-review report.

Different from the tax report — this is a performance document the user can
share with an advisor or keep for records.  Pages:
  1. Cover (totals + portfolio value chart image)
  2. Performance summary (vs S&P 500, best / worst holdings, dividend total)
  3. Holdings detail
  4. Transaction history for the year
  5. Dividend calendar (monthly bar chart image + upcoming projections)
"""
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta
from typing import Iterable

logger = logging.getLogger(__name__)

import matplotlib
matplotlib.use("Agg")  # headless renderer for PDF embedding
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend import market_data, profiles, store
from backend.portfolio import (
    build_portfolio,
    dividend_report,
    portfolio_value_history,
    benchmark_history,
)


# ---------- styling ----------

_styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=_styles["Heading1"], fontSize=22, leading=26, textColor=colors.HexColor("#0F172A"), spaceAfter=8)
H2 = ParagraphStyle("H2", parent=_styles["Heading2"], fontSize=14, leading=18, textColor=colors.HexColor("#0F172A"), spaceAfter=6)
NORMAL = ParagraphStyle("Normal", parent=_styles["BodyText"], fontSize=10, leading=14, textColor=colors.HexColor("#1F2937"))
MUTED = ParagraphStyle("Muted", parent=NORMAL, textColor=colors.HexColor("#6B7280"), fontSize=9)


def _money(amount: float, currency: str = "CAD") -> str:
    """Format a CAD/USD amount with a sign and two decimal places for PDF cells."""
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f} {currency}"


def _table_style() -> TableStyle:
    """Default reportlab TableStyle used by every section of the annual PDF."""
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#F9FAFB")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])


# ---------- chart helpers ----------

def _portfolio_value_chart_png(year: int) -> bytes | None:
    """Render the portfolio-value-vs-time chart for `year` as a PNG (matplotlib, headless).

    Returns None when there's no data in `year` or when matplotlib fails — the
    PDF builder falls back to a "chart unavailable" placeholder so the user
    sees a labelled blank rather than a silently-missing section.
    """
    try:
        points = portfolio_value_history()
        in_year = [p for p in points if p.date.year == year]
        if not in_year:
            return None
        dates = [p.date for p in in_year]
        totals = [p.total_cad for p in in_year]

        fig, ax = plt.subplots(figsize=(7, 2.6))
        ax.plot(dates, totals, color="#3B82F6", linewidth=1.8)
        ax.fill_between(dates, totals, color="#3B82F6", alpha=0.15)
        ax.set_title(f"Portfolio value — {year}", fontsize=11, color="#0F172A")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.autofmt_xdate()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception as e:
        logger.exception("annual_report portfolio_value chart failed: %s", e)
        return None


def _monthly_dividends_chart_png(year: int) -> bytes | None:
    """Render the monthly dividend bar chart for `year` as a PNG.

    Returns None when there's no data in `year` or when matplotlib fails.
    """
    try:
        rep = dividend_report()
        in_year = [m for m in rep.monthly if m.month.startswith(str(year))]
        if not in_year:
            return None
        labels = [m.month[5:] for m in in_year]  # MM
        values = [m.amount_cad for m in in_year]
        fig, ax = plt.subplots(figsize=(7, 2.6))
        ax.bar(labels, values, color="#10B981")
        ax.set_title(f"Dividend income — {year}", fontsize=11, color="#0F172A")
        ax.set_ylabel("CAD")
        ax.grid(True, axis="y", linestyle="--", alpha=0.4)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception as e:
        logger.exception("annual_report monthly_dividends chart failed: %s", e)
        return None


# ---------- public ----------

def build_annual_report_pdf(year: int) -> bytes:
    """Build the full 5-page annual report PDF for the active profile and return its bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title=f"Annual Portfolio Report {year}",
        author="Portfolio Dashboard",
    )

    profile = profiles.get_active_profile()
    data = build_portfolio()
    usd_cad = data.exchange_rate.usd_cad or 1.0
    txs = store.get_all_transactions()
    txs_year = [t for t in txs if t.transaction_date.year == year]

    elements: list = []

    # ----- Page 1: Cover -----
    elements.append(Paragraph(f"Annual Portfolio Report — {year}", H1))
    elements.append(Paragraph(f"Profile: <b>{profile.name}</b>", NORMAL))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", MUTED))
    elements.append(Spacer(1, 14))

    total_equity_cad = data.combined.total_equity_cad + data.combined.total_equity_usd * usd_cad
    net_deposits = data.combined.cash_deposited_cad + data.combined.cash_deposited_usd * usd_cad
    total_gain = total_equity_cad - net_deposits
    simple_ror = (total_gain / net_deposits * 100) if net_deposits > 0 else 0.0

    cover_data = [
        ["Total Portfolio Value", _money(total_equity_cad)],
        ["Net Deposits", _money(net_deposits)],
        ["Total Gain", _money(total_gain)],
        ["Simple Rate of Return", f"{simple_ror:+.2f}%"],
    ]
    cover_tbl = Table(cover_data, colWidths=[2.8 * inch, 2.4 * inch])
    cover_tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(cover_tbl)
    elements.append(Spacer(1, 18))

    chart_png = _portfolio_value_chart_png(year)
    if chart_png:
        img = Image(io.BytesIO(chart_png), width=6.8 * inch, height=2.5 * inch)
        elements.append(img)
    else:
        elements.append(Paragraph(
            f"[Portfolio-value chart unavailable — no transactions recorded in {year}.]",
            MUTED,
        ))
    elements.append(PageBreak())

    # ----- Page 2: Performance summary -----
    elements.append(Paragraph("Performance summary", H2))

    # vs S&P 500 for the year
    spy_year = [b for b in benchmark_history(start=f"{year}-01-01", ticker="SPY") if b.date.year == year]
    if len(spy_year) >= 2:
        spy_return = (spy_year[-1].value / spy_year[0].value - 1) * 100
    else:
        spy_return = None

    # Best / worst by period_return_pct over the year — re-use period=1y.
    holdings_year = build_portfolio(period="1y").holdings
    if holdings_year:
        sorted_by_return = sorted(
            [h for h in holdings_year if h.period_return_pct is not None],
            key=lambda h: h.period_return_pct or 0,
            reverse=True,
        )
        best = sorted_by_return[0] if sorted_by_return else None
        worst = sorted_by_return[-1] if sorted_by_return else None
    else:
        best = worst = None

    div_total_year = sum(
        (t.net_amount * usd_cad if t.currency == "USD" else t.net_amount)
        for t in txs_year
        if t.action == "DIVIDEND" and t.net_amount > 0
    )

    perf_rows = [
        ["Portfolio gain ({})".format(year), f"{simple_ror:+.2f}%"],
        ["S&P 500 (SPY) — same period", f"{spy_return:+.2f}%" if spy_return is not None else "—"],
    ]
    if best:
        perf_rows.append([
            f"Best performer", f"{best.ticker} ({best.account_type}) {best.period_return_pct:+.2f}%"
        ])
    if worst:
        perf_rows.append([
            f"Worst performer", f"{worst.ticker} ({worst.account_type}) {worst.period_return_pct:+.2f}%"
        ])
    perf_rows.append(["Total dividends ({})".format(year), _money(div_total_year)])

    perf_tbl = Table(perf_rows, colWidths=[2.8 * inch, 3.6 * inch])
    perf_tbl.setStyle(_table_style())
    elements.append(perf_tbl)
    elements.append(PageBreak())

    # ----- Page 3: Holdings detail -----
    elements.append(Paragraph("Holdings detail (year-end snapshot)", H2))
    rows: list[list] = [
        ["Ticker", "Account", "Shares", "ACB / share", "Current price", "Market value (CAD)", "ROI %", "Dividends"]
    ]
    for h in data.holdings:
        mv_cad = h.market_value_cad or 0
        rows.append([
            h.ticker,
            h.account_type,
            f"{h.total_shares:g}",
            _money(h.acb_per_share, h.currency),
            _money(h.current_price or 0, h.currency),
            _money(mv_cad, "CAD"),
            f"{h.roi_pct:+.2f}%" if h.roi_pct is not None else "—",
            _money(h.dividends_received, h.currency),
        ])
    holdings_tbl = Table(rows, colWidths=[0.8*inch, 0.7*inch, 0.6*inch, 1.0*inch, 1.0*inch, 1.1*inch, 0.7*inch, 1.0*inch])
    holdings_tbl.setStyle(_table_style())
    elements.append(holdings_tbl)
    elements.append(PageBreak())

    # ----- Page 4: Transaction history -----
    elements.append(Paragraph(f"Transaction history — {year}", H2))
    if txs_year:
        rows = [["Date", "Action", "Ticker", "Account", "Quantity", "Price", "Net amount", "Currency"]]
        for t in sorted(txs_year, key=lambda x: x.transaction_date):
            rows.append([
                t.transaction_date.isoformat(),
                t.action,
                t.resolved_ticker or "—",
                t.account_type,
                f"{t.quantity:g}",
                _money(t.price, t.currency) if t.price else "—",
                _money(t.net_amount, t.currency),
                t.currency,
            ])
        tx_tbl = Table(rows, colWidths=[0.9*inch, 0.8*inch, 0.9*inch, 0.7*inch, 0.8*inch, 1.0*inch, 1.0*inch, 0.7*inch])
        tx_tbl.setStyle(_table_style())
        elements.append(tx_tbl)
    else:
        elements.append(Paragraph(f"No transactions recorded for {year}.", MUTED))
    elements.append(PageBreak())

    # ----- Page 5: Dividend calendar -----
    elements.append(Paragraph(f"Dividend calendar — {year}", H2))
    div_png = _monthly_dividends_chart_png(year)
    if div_png:
        elements.append(Image(io.BytesIO(div_png), width=6.8 * inch, height=2.5 * inch))
        elements.append(Spacer(1, 12))
    else:
        elements.append(Paragraph(
            f"[Dividend chart unavailable — no dividend rows recorded in {year}.]",
            MUTED,
        ))
        elements.append(Spacer(1, 12))
    div_rep = dividend_report()
    if div_rep.upcoming:
        elements.append(Paragraph("Upcoming projected payments", H2))
        rows = [["Ticker", "Estimated date", "Estimated amount (CAD)", "Cadence (days)"]]
        for u in div_rep.upcoming:
            rows.append([u.ticker, u.next_date.isoformat(), _money(u.estimated_amount_cad, "CAD"), str(u.cadence_days)])
        ut = Table(rows, colWidths=[1.2*inch, 1.4*inch, 1.8*inch, 1.4*inch])
        ut.setStyle(_table_style())
        elements.append(ut)

    elements.append(Spacer(1, 18))
    elements.append(Paragraph(
        "Generated locally on your computer — no portfolio data was sent to any external service. "
        "Prices and benchmark via Yahoo Finance.",
        MUTED,
    ))

    doc.build(elements)
    return buf.getvalue()


def suggested_filename(year: int) -> str:
    """Filename suggestion the API surfaces in Content-Disposition (annual_report_YYYY.pdf)."""
    return f"annual_report_{year}.pdf"
