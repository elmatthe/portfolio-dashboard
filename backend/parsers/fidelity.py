"""Fidelity Investments (US) — CSV.

Quirks:
- US broker; all transactions are USD (no Currency column).
- All commissions are 0.0 (zero-commission product).
- Dates in MM/DD/YYYY format.
- Account types are US-specific: Individual / Roth IRA / Traditional IRA.
- 3-line metadata header before the column row.
- No FX columns — FXService fills net_cad.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import ClassVar

import pandas as pd

from backend.fx import get_fx_service
from backend.models import Transaction
from backend.parsers._common import (
    compute_hash,
    guess_account_type,
    guess_exchange,
    normalize_action,
    parse_date,
    safe_float,
    safe_str,
)
from backend.parsers.base import BaseParser
from backend.parsers.rbc import _find_csv_header_row
from backend.parsers.registry import _register

logger = logging.getLogger(__name__)


@_register
class FidelityParser(BaseParser):
    BROKER_NAME: ClassVar[str] = "Fidelity Investments"
    BROKER_KEY: ClassVar[str] = "fidelity"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        if Path(file_path).suffix.lower() != ".csv":
            return 0.0
        s = content_sample.lower()
        if "fidelity investments" in s:
            return 0.95
        if "run date" in s and "amount ($)" in s:
            return 0.85
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        path = Path(file_path)
        if path.suffix.lower() != ".csv":
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        account_number = "fidelity"
        for line in text.splitlines()[:4]:
            m = re.search(r"Account:\s*(\S+)", line)
            if m:
                account_number = m.group(1)
                break
        header_idx = _find_csv_header_row(text, must_contain=("Run Date", "Action"))
        if header_idx is None:
            logger.warning("Fidelity parser: no header row found in %s", path)
            return []
        df = pd.read_csv(path, skiprows=header_idx)
        return _parse_fidelity_rows(df, account_number)


def _parse_fidelity_rows(df: pd.DataFrame, account_number: str) -> list[Transaction]:
    fx = get_fx_service()
    out: list[Transaction] = []
    for _, row in df.iterrows():
        trade_date = parse_date(row.get("Run Date"))
        if trade_date is None:
            continue
        symbol = safe_str(row.get("Symbol"))
        description = safe_str(row.get("Security Description")) or ""
        quantity = safe_float(row.get("Quantity"))
        price = safe_float(row.get("Price ($)"))
        amount = safe_float(row.get("Amount ($)"))
        commission = safe_float(row.get("Commission ($)"))
        account_type = guess_account_type(safe_str(row.get("Account Type")), default="Individual")

        action = normalize_action(safe_str(row.get("Action")), quantity=quantity, net=amount)
        if action == "BUY" and amount > 0:
            amount = -amount

        fx_rate = fx.rate_to_cad("USD", trade_date)
        net_cad = round(amount * fx_rate, 2)

        full_account = f"{account_number}-{account_type}"
        h = compute_hash(
            transaction_date=trade_date,
            action=action,
            raw_symbol=symbol,
            quantity=quantity,
            net_amount=amount,
            account_number=full_account,
        )
        out.append(
            Transaction(
                hash=h,
                broker="fidelity",
                transaction_date=trade_date,
                action=action,
                raw_symbol=symbol,
                description=description,
                quantity=quantity,
                price=price,
                gross_amount=abs(amount),
                commission=commission,
                net_amount=amount,
                currency="USD",
                account_number=full_account,
                account_type=account_type,
                fx_rate_to_cad=fx_rate,
                net_cad=net_cad,
                exchange=guess_exchange(symbol, "USD"),
            )
        )
    return out
