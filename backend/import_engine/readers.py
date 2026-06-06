"""File-reader adapters for the universal import lane (Item 4, Step 2).

Turns any supported tabular file into a uniform RAW GRID — a list of rows, each
a list of stringified cells — WITHOUT yet deciding which row is the header. Header
detection and table cleanup live in `table_extract.py`; this module only handles
the format/encoding/sheet mechanics:

  - csv / tsv : BOM strip + encoding fallback + delimiter sniff (reusing
                `backend.parsers._common.read_text_sample` and `sniff_csv_delimiter`
                — NOT reinvented), then `csv.reader` for quote-aware splitting.
  - xlsx/xlsm : every worksheet via openpyxl (read-only, data-only) → one RawTable
                per sheet; `table_extract.pick_best_sheet` chooses the transaction
                table later.
  - xls       : best-effort via pandas (needs `xlrd`); raises a clear error if the
                engine is unavailable rather than failing cryptically.

No alias logic, no normalization, no pandas dtype coercion of values — every cell
is a faithful trimmed string so the classifier/normalizer downstream see the raw
text exactly as the file presented it.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from backend.parsers._common import read_text_sample, sniff_csv_delimiter

logger = logging.getLogger(__name__)

# Extensions we can turn into a raw grid here. (.pdf is wired in at Step 6.)
SUPPORTED_TABULAR_EXTS = frozenset({".csv", ".tsv", ".xlsx", ".xlsm", ".xls"})


@dataclass
class RawTable:
    """A raw, header-unaware grid read from one file (or one Excel sheet)."""

    rows: list[list[str]]
    fmt: str                      # "csv" | "tsv" | "xlsx" | "xlsm" | "xls"
    sheet_name: str | None = None
    n_sheets: int = 1
    extras: dict = field(default_factory=dict)

    @property
    def n_rows(self) -> int:
        return len(self.rows)


# --------------------------------------------------------------------------- #
# Cell coercion                                                                #
# --------------------------------------------------------------------------- #

def _cell(value: object) -> str:
    """Faithful trimmed-string form of a raw cell. None/NaN → ''."""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value).strip()


# --------------------------------------------------------------------------- #
# Delimited text (csv / tsv)                                                   #
# --------------------------------------------------------------------------- #

def _decode_file(path: Path) -> str:
    """Read a text file as a string: strip a UTF-8 BOM, fall back to latin-1."""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def read_delimited(path: Path) -> list[RawTable]:
    """Read a csv/tsv into a single RawTable, sniffing the delimiter.

    Reuses `_common.read_text_sample` (BOM/encoding-safe head) for the sniff
    sample and `_common.sniff_csv_delimiter` for the delimiter choice.
    """
    sample = read_text_sample(path, max_bytes=8192)
    delim = sniff_csv_delimiter(sample)
    text = _decode_file(path)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [[_cell(c) for c in row] for row in reader]
    fmt = "tsv" if delim == "\t" else "csv"
    return [RawTable(rows=rows, fmt=fmt, sheet_name=None, n_sheets=1,
                     extras={"delimiter": delim})]


# --------------------------------------------------------------------------- #
# Excel (xlsx / xlsm / xls)                                                    #
# --------------------------------------------------------------------------- #

def _read_xlsx_like(path: Path, fmt: str) -> list[RawTable]:
    """Read every worksheet of an xlsx/xlsm via openpyxl into RawTables."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet_names = list(wb.sheetnames)
        tables: list[RawTable] = []
        for name in sheet_names:
            ws = wb[name]
            rows = [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True)]
            tables.append(
                RawTable(rows=rows, fmt=fmt, sheet_name=name, n_sheets=len(sheet_names))
            )
        return tables
    finally:
        wb.close()


def _read_xls(path: Path) -> list[RawTable]:
    """Best-effort legacy .xls via pandas (requires the `xlrd` engine)."""
    try:
        import pandas as pd
    except Exception as e:  # pragma: no cover - pandas is a hard dep elsewhere
        raise RuntimeError(f"pandas unavailable for .xls: {e}")
    try:
        sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    except ImportError as e:
        raise RuntimeError(
            "Reading legacy .xls files needs the 'xlrd' package. Re-save the file "
            "as .xlsx, or install xlrd. (Original error: %s)" % e
        )
    tables: list[RawTable] = []
    for name, df in sheets.items():
        rows = [[_cell(c) for c in row] for row in df.itertuples(index=False, name=None)]
        tables.append(RawTable(rows=rows, fmt="xls", sheet_name=str(name), n_sheets=len(sheets)))
    return tables


# --------------------------------------------------------------------------- #
# Dispatch                                                                     #
# --------------------------------------------------------------------------- #

def read_tabular(path: str | Path) -> list[RawTable]:
    """Read any supported tabular file into one RawTable per sheet (1 for csv/tsv).

    Raises ValueError for an unsupported extension (pdf is handled separately in
    Step 6 — not here).
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".csv", ".tsv"):
        return read_delimited(p)
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx_like(p, fmt=ext.lstrip("."))
    if ext == ".xls":
        return _read_xls(p)
    raise ValueError(f"read_tabular: unsupported extension {ext!r} for {p.name}")
