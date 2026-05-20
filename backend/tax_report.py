"""CRA Capital Gains / Losses PDF — Schedule 3-style report.

Builds a year-scoped PDF with:
  • Cover page (totals + 50% inclusion line)
  • Section A: Realized gains, one row per sell (Schedule 3 column order)
  • Section B: Superficial loss adjustments (if any)
  • Section C: TFSA activity summary (clearly labelled non-taxable)
  • Section D: Dividend income (eligible vs foreign US)

Uses reportlab's platypus flowable system so the layout reflows naturally
across pages without us having to hand-place coordinates.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

from backend import market_data, profiles, store
from backend.acb import compute as compute_acb
from backend.models import RealizedGain


# ---------- styling ----------

_styles = getSampleStyleSheet()

H1 = ParagraphStyle(
    "H1", parent=_styles["Heading1"], fontSize=20, leading=24, spaceAfter=12, textColor=colors.HexColor("#0F172A"),
)
H2 = ParagraphStyle(
    "H2", parent=_styles["Heading2"], fontSize=14, leading=18, spaceAfter=8, textColor=colors.HexColor("#0F172A"),
)
NORMAL = ParagraphStyle(
    "Normal", parent=_styles["BodyText"], fontSize=10, leading=14, textColor=colors.HexColor("#1F2937"),
)
MUTED = ParagraphStyle(
    "Muted", parent=NORMAL, textColor=colors.HexColor("#6B7280"), fontSize=9,
)
DISCLAIMER = ParagraphStyle(
    "Disclaimer", parent=MUTED, fontSize=9, leading=12, alignment=0, leftIndent=0, rightIndent=0,
)

TABLE_HEADER_BG = colors.HexColor("#0F172A")
TABLE_HEADER_FG = colors.HexColor("#F9FAFB")
ALT_ROW = colors.HexColor("#F8FAFC")
GAIN_BG = colors.HexColor("#DCFCE7")
LOSS_BG = colors.HexColor("#FEE2E2")


def _money(amount: float, currency: str = "CAD") -> str:
    """Same money formatter used by the annual report; lives here to keep the modules independent."""
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f} {currency}"


def _table_style(highlight_negatives_col: int | None = None) -> TableStyle:
    """Default TableStyle used by every section of the tax PDF."""
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TABLE_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    return TableStyle(style)


# ---------- public entry ----------

def build_tax_report_pdf(year: int) -> bytes:
    """Generate the PDF and return its bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"Capital Gains Report {year}",
        author="Portfolio Dashboard",
    )

    elements: list = []
    profile = profiles.get_active_profile()
    txs = store.get_all_transactions()
    holdings, gains_report = compute_acb(txs, security_names=_security_names(txs))

    # All gains/losses for the year
    year_gains: list[RealizedGain] = [
        g for g in gains_report.realized_gains if g.transaction_date.year == year
    ]
    total_taxable = sum(g.total_gain for g in year_gains if g.taxable)
    total_non_taxable = sum(g.total_gain for g in year_gains if not g.taxable)
    inclusion_amount = total_taxable * 0.5  # CRA 50% inclusion rate

    # ---- Cover ----
    elements.append(Paragraph(f"Capital Gains / Losses Report — Tax Year {year}", H1))
    elements.append(Paragraph(f"Profile: <b>{profile.name}</b>", NORMAL))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", MUTED))
    elements.append(Spacer(1, 18))

    summary_data = [
        ["Total Taxable Gains/Losses", _money(total_taxable, "CAD")],
        ["Total TFSA / Registered Gains (non-taxable)", _money(total_non_taxable, "CAD")],
        ["Net Taxable Amount", _money(total_taxable, "CAD")],
        ["50% Inclusion Amount (line 12700 of T1)", _money(inclusion_amount, "CAD")],
    ]
    t = Table(summary_data, colWidths=[3.6 * inch, 2.4 * inch])
    t.setStyle(
        TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
            ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#FEF3C7")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ])
    )
    elements.append(t)
    elements.append(Spacer(1, 18))

    elements.append(Paragraph(
        "<b>Disclaimer:</b> This report is for informational purposes only. "
        "Verify all figures with a qualified tax professional before filing your tax return. "
        "Adjusted cost base (ACB) is calculated using CRA rules including the superficial "
        "loss rule. Capital gains within a TFSA or RRSP are not taxable and are listed here "
        "for completeness only.",
        DISCLAIMER,
    ))
    elements.append(PageBreak())

    # ---- Section A: realized gains ----
    elements.append(Paragraph("Section A — Realized Gains &amp; Losses (Schedule 3 format)", H2))
    if not year_gains:
        elements.append(Paragraph(
            f"No realized capital gains or losses recorded for {year}.", NORMAL,
        ))
    else:
        header = [
            "Description",
            "Date acquired",
            "Date disposed",
            "Proceeds",
            "ACB",
            "Outlays / expenses",
            "Gain / (loss)",
        ]
        rows: list[list] = [header]
        for g in year_gains:
            proceeds = g.sale_price * g.shares_sold
            acb_total = g.acb_per_share * g.shares_sold
            outlays = g.commission
            rows.append([
                f"{g.shares_sold:g} × {g.ticker}\n({g.account_type})",
                "(see ACB)",  # could be improved with FIFO matching
                g.transaction_date.isoformat(),
                _money(proceeds, g.currency),
                _money(acb_total, g.currency),
                _money(outlays, g.currency),
                _money(g.total_gain, g.currency),
            ])
        # Subtotal row
        subtotal_taxable = sum(g.total_gain for g in year_gains if g.taxable)
        subtotal_all = sum(g.total_gain for g in year_gains)
        rows.append([
            "", "", "", "", "", "Subtotal (taxable)", _money(subtotal_taxable, "CAD")
        ])
        rows.append([
            "", "", "", "", "", "Subtotal (all)", _money(subtotal_all, "CAD")
        ])
        t = Table(rows, colWidths=[1.4*inch, 0.9*inch, 0.9*inch, 1.1*inch, 1.1*inch, 1.1*inch, 1.1*inch])
        style = _table_style()
        for i, g in enumerate(year_gains, start=1):
            style.add("BACKGROUND", (-1, i), (-1, i), GAIN_BG if g.total_gain >= 0 else LOSS_BG)
            style.add("ALIGN", (3, i), (-1, i), "RIGHT")
        style.add("FONTNAME", (5, -2), (-1, -1), "Helvetica-Bold")
        style.add("ALIGN", (3, -2), (-1, -1), "RIGHT")
        t.setStyle(style)
        elements.append(t)
    elements.append(Spacer(1, 18))

    # ---- Section B: superficial loss adjustments ----
    sloss = [
        a for h in holdings.values() for a in h.superficial_loss_adjustments
        if a.transaction_date.year == year
    ]
    if sloss:
        elements.append(Paragraph("Section B — Superficial Loss Adjustments", H2))
        rows = [["Date of loss", "Security", "Denied loss", "Repurchase date", "Note"]]
        for a in sloss:
            rows.append([
                a.transaction_date.isoformat(),
                a.ticker,
                _money(a.denied_loss, "CAD"),
                a.repurchase_date.isoformat() if a.repurchase_date else "—",
                a.note,
            ])
        t = Table(rows, colWidths=[1.0*inch, 1.1*inch, 1.2*inch, 1.1*inch, 3.2*inch])
        t.setStyle(_table_style())
        elements.append(t)
        elements.append(Spacer(1, 18))

    # ---- Section C: TFSA activity ----
    elements.append(Paragraph("Section C — TFSA Activity Summary", H2))
    elements.append(Paragraph(
        "Capital gains and losses within a TFSA are <b>not reported</b> on your tax return.",
        NORMAL,
    ))
    tfsa_txs = [
        t for t in txs
        if t.account_type == "TFSA"
        and t.transaction_date.year == year
        and t.action in ("BUY", "SELL", "DIVIDEND", "CONTRIBUTION")
    ]
    if tfsa_txs:
        rows = [["Date", "Action", "Security", "Quantity", "Net amount", "Currency"]]
        for t in sorted(tfsa_txs, key=lambda x: x.transaction_date):
            rows.append([
                t.transaction_date.isoformat(),
                t.action,
                t.resolved_ticker or "—",
                f"{t.quantity:g}",
                _money(t.net_amount, t.currency),
                t.currency,
            ])
        tbl = Table(rows, colWidths=[0.9*inch, 1.0*inch, 1.1*inch, 1.0*inch, 1.2*inch, 0.8*inch])
        tbl.setStyle(_table_style())
        elements.append(tbl)
    else:
        elements.append(Paragraph(f"No TFSA activity recorded for {year}.", MUTED))
    elements.append(Spacer(1, 18))

    # ---- Section D: dividend income ----
    elements.append(Paragraph("Section D — Dividend Income Summary", H2))
    usd_cad, _ = market_data.get_fx("USDCAD")

    div_by_ticker: dict[tuple[str, str], dict] = {}
    for t in txs:
        if t.action != "DIVIDEND" or t.transaction_date.year != year:
            continue
        key = (t.resolved_ticker or t.raw_symbol or "?", t.currency)
        entry = div_by_ticker.setdefault(key, {"amount": 0.0, "account_type": t.account_type})
        entry["amount"] += t.net_amount

    if div_by_ticker:
        rows = [["Security", "Account", "Currency", "Amount", "Classification"]]
        canadian_total = 0.0
        foreign_total = 0.0
        for (ticker, currency), info in sorted(div_by_ticker.items()):
            classification = (
                "Eligible Canadian dividend"
                if currency == "CAD"
                else "Foreign income (US)"
            )
            rows.append([
                ticker,
                info["account_type"],
                currency,
                _money(info["amount"], currency),
                classification,
            ])
            if currency == "CAD":
                canadian_total += info["amount"]
            else:
                foreign_total += info["amount"] * usd_cad
        rows.append(["", "", "", "Total CAD-eq:", _money(canadian_total + foreign_total, "CAD")])
        tbl = Table(rows, colWidths=[1.0*inch, 1.0*inch, 0.8*inch, 1.3*inch, 1.9*inch])
        st = _table_style()
        st.add("FONTNAME", (-2, -1), (-1, -1), "Helvetica-Bold")
        tbl.setStyle(st)
        elements.append(tbl)
    else:
        elements.append(Paragraph(f"No dividends recorded for {year}.", MUTED))

    elements.append(Spacer(1, 24))
    elements.append(Paragraph(
        "End of report. Cross-reference Section A against your T5008 slips and Section D "
        "against any T3/T5 slips received from your broker.",
        MUTED,
    ))

    doc.build(elements)
    return buf.getvalue()


def _security_names(txs: Iterable) -> dict[str, str]:
    """Build a ticker → description map from the transaction set for use in Schedule 3."""
    names: dict[str, str] = {}
    for t in txs:
        if not t.resolved_ticker or t.resolved_ticker in names:
            continue
        desc = (t.description or "").strip()
        if desc:
            names[t.resolved_ticker] = desc[:60]
    return names


def suggested_filename(year: int) -> str:
    """Filename surfaced in Content-Disposition (tax_report_YYYY.pdf)."""
    return f"tax_report_{year}.pdf"
