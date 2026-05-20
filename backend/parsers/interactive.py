"""Interactive Brokers — Flex CSV export.

Patterns extracted from the Next.js/IBKR repo (§0.5 Tier 2 repo 6):
- Two-block CSV: first block is `Statement,Header/Data` metadata, second
  block (after a blank line) is the trade table.
- The trade-block header lives in column position 0 as `DataDiscriminator`;
  only rows whose first column equals "Trade" become transactions.
- `Quantity` is signed: **negative = BUY**, positive = SELL. We normalize to
  positive quantity and emit the canonical BUY/SELL action.
- `Account` column carries the account TYPE (Margin/RRSP/TFSA/RESP/…) rather
  than a number; the AccountID comes from the metadata block (`U1234567`).
"""
from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from backend.fx import get_fx_service
from backend.models import Transaction
from backend.parsers._common import (
    compute_hash,
    guess_account_type,
    guess_currency,
    guess_exchange,
    safe_float,
    safe_str,
)
from backend.parsers.base import BaseParser
from backend.parsers.registry import _register

logger = logging.getLogger(__name__)


@_register
class InteractiveBrokersParser(BaseParser):
    BROKER_NAME: ClassVar[str] = "Interactive Brokers"
    BROKER_KEY: ClassVar[str] = "interactive"
    SUPPORTED_FORMATS: ClassVar[list[str]] = ["csv"]

    @classmethod
    def detect(cls, file_path: str | Path, content_sample: str) -> float:
        if Path(file_path).suffix.lower() != ".csv":
            return 0.0
        s = content_sample.lower()
        # Strong signals — the file is unmistakably IB
        if "interactive brokers" in s or "brokername,interactive" in s:
            return 0.95
        if "statement,header" in s and "datadiscriminator" in s:
            return 0.9
        if "datadiscriminator" in s and "comm/fee" in s:
            return 0.8
        return 0.0

    def parse(self, file_path: str | Path) -> list[Transaction]:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")

        # Pull AccountID from the metadata block — used as account_number for the hash.
        account_id = "interactive"
        m = re.search(r"Statement,Data,AccountID,([^\r\n,]+)", text)
        if m:
            account_id = m.group(1).strip()

        # Locate the trade-table header (first row that starts with DataDiscriminator).
        lines = text.splitlines()
        header_idx = None
        for i, line in enumerate(lines):
            if line.startswith("DataDiscriminator"):
                header_idx = i
                break
        if header_idx is None:
            logger.warning("IB parser: no DataDiscriminator header found in %s", path)
            return []

        reader = csv.DictReader(lines[header_idx:])
        fx = get_fx_service()
        out: list[Transaction] = []
        for row in reader:
            if (row.get("DataDiscriminator") or "").strip() != "Trade":
                continue
            raw_date = safe_str(row.get("TradeDate")) or ""
            try:
                trade_date = datetime.strptime(raw_date, "%Y%m%d").date()
            except ValueError:
                continue
            symbol = safe_str(row.get("Symbol"))
            description = safe_str(row.get("Description")) or ""
            currency = guess_currency(row.get("Currency"), default="USD")
            signed_qty = safe_float(row.get("Quantity"))
            price = safe_float(row.get("T. Price"))
            proceeds = safe_float(row.get("Proceeds"))
            commission = abs(safe_float(row.get("Comm/Fee")))
            account_type_label = safe_str(row.get("Account")) or "Non-Registered"
            account_type = guess_account_type(account_type_label, default="Non-Registered")

            # Negative qty = BUY in IB convention; positive = SELL.
            if signed_qty < 0:
                action = "BUY"
            elif signed_qty > 0:
                action = "SELL"
            else:
                action = "OTHER"
            quantity = abs(signed_qty)
            # Net amount stays signed to preserve cash-flow direction
            # (buy = negative net, sell = positive net).
            net_amount = proceeds  # already signed correctly in the IB file
            gross_amount = proceeds - (-commission if proceeds < 0 else commission)

            # IB CSVs don't include an FX column — fall back to FXService.
            fx_rate = fx.rate_to_cad(currency, trade_date)
            net_cad = round(net_amount * fx_rate, 2)

            account_number = f"{account_id}-{account_type}"  # stable per (account, type)

            h = compute_hash(
                transaction_date=trade_date,
                action=action,
                raw_symbol=symbol,
                quantity=quantity,
                net_amount=net_amount,
                account_number=account_number,
            )
            out.append(
                Transaction(
                    hash=h,
                    broker="interactive",
                    transaction_date=trade_date,
                    action=action,
                    raw_symbol=symbol,
                    description=description,
                    quantity=quantity,
                    price=price,
                    gross_amount=gross_amount,
                    commission=commission,
                    net_amount=net_amount,
                    currency=currency,
                    account_number=account_number,
                    account_type=account_type,
                    fx_rate_to_cad=fx_rate,
                    net_cad=net_cad,
                    reference_id=safe_str(row.get("Conid")),
                    exchange=guess_exchange(symbol, currency),
                )
            )
        return out
