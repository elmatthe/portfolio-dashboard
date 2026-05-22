"""TFSA contribution-room calculator.

Combines CRA's annual limit schedule with the user's TFSA transactions to
report: total room accumulated, used room, current-year usage, withdrawals
added back next year, over-contribution amount (if any), and a year-by-year
breakdown.

Notes on CRA rules implemented:
  - You earn TFSA room starting the year you turn 18 OR the year you became a
    Canadian resident, whichever is later. (Income/residency rules beyond
    that — temporary residence, multi-year non-residency — are not modelled.)
  - Withdrawals do NOT free up room until January 1 of the FOLLOWING year.
  - Over-contributions are subject to a 1%-per-month penalty (we surface the
    amount; we don't compute the penalty since timing rules within a month
    require sub-day precision the user can audit themselves).
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from pydantic import BaseModel, Field

from backend import store


# Cumulative annual limits set by CRA. Update each year when the new limit is
# announced (usually in November of the previous year).
TFSA_ANNUAL_LIMITS: dict[int, int] = {
    2009: 5000,
    2010: 5000,
    2011: 5000,
    2012: 5000,
    2013: 5500,
    2014: 5500,
    2015: 10000,
    2016: 5500,
    2017: 5500,
    2018: 5500,
    2019: 6000,
    2020: 6000,
    2021: 6000,
    2022: 6000,
    2023: 6500,
    2024: 7000,
    2025: 7000,
    2026: 7000,
}


class TfsaAnnualRow(BaseModel):
    year: int
    annual_limit_cad: float
    contributions_cad: float
    withdrawals_cad: float


class TfsaRoomReport(BaseModel):
    """TFSA contribution room report.

    Field semantics:
      - `cumulative_limit_to_date`: pure sum of CRA annual limits since
        eligibility (no withdrawal credits folded in).
      - `total_room_accumulated`: cumulative_limit + prior-year withdrawal credits
        (kept for backward compat — prefer cumulative_limit_to_date + the
        withdrawals_last_year_added_back field for clarity).
      - `available_room`: room currently available to contribute today; capped at 0.
        Use this as the headline figure in any UI.
      - `is_estimate`: True when settings are incomplete (birth_year or
        resident_since unset). The eligibility_start_year then defaults to 2009
        which overstates room for younger users — the UI must surface this.
    """

    total_room_accumulated: float
    cumulative_limit_to_date: float
    available_room: float
    total_contributions: float
    total_withdrawals: float
    contribution_room_remaining: float
    current_year_limit: float
    contributions_this_year: float
    withdrawals_last_year_added_back: float
    over_contributed: bool
    over_contribution_amount: float
    annual_breakdown: list[TfsaAnnualRow] = Field(default_factory=list)
    eligibility_start_year: int  # Year the user first earned room (max of age-18 and residency)
    missing_settings: list[str] = Field(default_factory=list)
    is_estimate: bool = False
    calculation_note: str = ""


def compute_tfsa_room(
    birth_year: int | None,
    resident_since: int | None,
    today: date | None = None,
) -> TfsaRoomReport:
    """Build the user's TFSA contribution-room report.

    Reads CONTRIBUTION + WITHDRAWAL transactions from every TFSA-typed
    account in the active profile's database. When `birth_year` is missing,
    the report falls back to 2009 eligibility (the safest default for users
    who turned 18 before 2009) and sets `is_estimate=True` so the UI can
    surface a warning — without this, a 25-year-old with empty settings
    would see ~$109k of room.
    """
    t = today or date.today()
    current_year = t.year
    current_year_limit = float(TFSA_ANNUAL_LIMITS.get(current_year, 0))

    missing: list[str] = []
    if birth_year is None:
        missing.append("tfsa_birth_year")
    if resident_since is None:
        missing.append("tfsa_resident_since")

    # Eligibility starts the later of: year-turned-18 OR resident_since OR 2009.
    # `birth_year` is sanity-bounded — silly values (negative, in the future)
    # collapse to the 2009 baseline rather than producing absurd dates.
    if birth_year is not None and (birth_year < 1900 or birth_year > current_year):
        # Treat as missing so the UI surfaces the same correction prompt.
        birth_year = None
        if "tfsa_birth_year" not in missing:
            missing.append("tfsa_birth_year")
    age18_year = (birth_year + 18) if birth_year else 2009
    eligibility_start = max(age18_year, resident_since or 2009, 2009)
    is_estimate = bool(missing)

    # FX service for USD TFSA contributions (rare, but the spec says use the
    # contribution-date rate, not 1:1).
    from backend.fx import get_fx_service
    fx = get_fx_service()

    # Walk every CRA year from eligibility to today, accumulating room.
    contribs_by_year: dict[int, float] = {}
    withdraws_by_year: dict[int, float] = {}
    for tx in store.get_all_transactions():
        if tx.account_type != "TFSA":
            continue
        amt = tx.net_amount
        if tx.currency != "CAD":
            # USD/GBP/etc. TFSA activity is rare but must be converted at the
            # contribution-date rate (CRA-correct), not 1:1.
            rate = fx.rate_to_cad(tx.currency, tx.transaction_date)
            amt = amt * rate
        y = tx.transaction_date.year
        if tx.action == "CONTRIBUTION" and amt > 0:
            contribs_by_year[y] = contribs_by_year.get(y, 0.0) + amt
        elif tx.action == "DEPOSIT" and amt > 0:
            # Treat plain DEPOSITs into a TFSA as contributions (Questrade
            # sometimes labels them this way before the CRA "CON" code lands).
            contribs_by_year[y] = contribs_by_year.get(y, 0.0) + amt
        elif tx.action == "WITHDRAWAL":
            withdraws_by_year[y] = withdraws_by_year.get(y, 0.0) + abs(amt)

    # Withdrawals from year Y free up room on Jan 1 of year Y+1 — so for
    # current_year, we add back withdrawals from current_year - 1.
    withdrawals_last_year_added_back = withdraws_by_year.get(current_year - 1, 0.0)

    # Year-by-year breakdown
    breakdown: list[TfsaAnnualRow] = []
    total_limit_accumulated = 0.0
    total_contribs = 0.0
    total_withdraws = 0.0
    for y in range(eligibility_start, current_year + 1):
        limit = float(TFSA_ANNUAL_LIMITS.get(y, 0))
        c = contribs_by_year.get(y, 0.0)
        w = withdraws_by_year.get(y, 0.0)
        total_limit_accumulated += limit
        total_contribs += c
        total_withdraws += w
        breakdown.append(
            TfsaAnnualRow(
                year=y,
                annual_limit_cad=round(limit, 2),
                contributions_cad=round(c, 2),
                withdrawals_cad=round(w, 2),
            )
        )

    # Room remaining = cumulative limits - net contributions + withdrawals
    # from PRIOR years (current-year withdrawals don't restore room until next year).
    withdraw_prior_years = sum(
        amt for y, amt in withdraws_by_year.items() if y < current_year
    )
    room_remaining = total_limit_accumulated - total_contribs + withdraw_prior_years

    over_contributed = room_remaining < 0
    over_amount = max(0.0, -room_remaining)
    available_room = max(0.0, room_remaining)

    note = (
        "Withdrawals restore room on January 1 of the following calendar year. "
        "Over-contributions are subject to a 1%-per-month CRA penalty."
    )
    if is_estimate:
        note = (
            "Birth year / residency-since is unset; the calculation assumes "
            "eligibility began in 2009 (the safe default for users 18+ before 2009). "
            "Set these in Settings → TFSA for an accurate figure. "
        ) + note

    return TfsaRoomReport(
        total_room_accumulated=round(total_limit_accumulated + withdraw_prior_years, 2),
        cumulative_limit_to_date=round(total_limit_accumulated, 2),
        available_room=round(available_room, 2),
        total_contributions=round(total_contribs, 2),
        total_withdrawals=round(total_withdraws, 2),
        contribution_room_remaining=round(available_room, 2),
        current_year_limit=current_year_limit,
        contributions_this_year=round(contribs_by_year.get(current_year, 0.0), 2),
        withdrawals_last_year_added_back=round(withdrawals_last_year_added_back, 2),
        over_contributed=over_contributed,
        over_contribution_amount=round(over_amount, 2),
        annual_breakdown=breakdown,
        eligibility_start_year=eligibility_start,
        missing_settings=missing,
        is_estimate=is_estimate,
        calculation_note=note,
    )
