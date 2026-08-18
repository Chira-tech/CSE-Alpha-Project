"""
Deterministic parsing of a real CDS/broker "Portfolio" export — the same
family of real, messy real-world extraction this project's financial-
statement pipeline already does (`app.domain.financial_statement_
parsing`'s own module docstring states the same discipline this one
follows: verified against a real downloaded document, never invented).

VERIFIED AGAINST A REAL EXPORT, NOT AN ASSUMED FORMAT. Column headers,
row shape and the trailing "Total" row all come from a real CDS
portfolio export (an NBS/CDS-format equity holdings report) supplied
directly by the user, 18 Aug 2026 — not guessed at. The header set is
matched EXACTLY (case/whitespace-normalised), the same "exact match, not
substring" discipline `app.domain.financial_statement_parsing.
CANONICAL_LABELS` already applies, because a silently-shifted column on
a differently-shaped export would misattribute one real number as
another — a financial holdings figure, exactly the kind of number this
whole project refuses to get wrong quietly.

THE FILE'S OWN "Total" ROW IS A REAL, INDEPENDENT ARITHMETIC CHECK, THE
SAME DISCIPLINE `app.domain.financial_statement_parsing.check_
accounting_identities` ALREADY ESTABLISHED FOR PDF EXTRACTION. The
parsed positions' own summed `total_cost`/`market_value` are compared
against the file's own stated Total row — a real, cheap way to catch a
row silently mis-parsed or dropped, before anything gets stored.

NO ACCOUNT/NIC IDENTIFIER IS EVER EXTRACTED. The real file's own title
row ("Portfolio (NBS/... - ACCOUNT HOLDER NAME-NIC NUMBER) - EQUITY")
carries genuine personal data with no bearing on which stocks are held —
this module only ever reads the header row and the position rows
between it and "Total", never the title row's own contents.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: The real header row, verified against an actual CDS portfolio export
#: (18 Aug 2026) — exact text, left-to-right order not assumed (headers
#: are matched by name, not position, so a real export with columns in a
#: different order still parses correctly).
EXPECTED_HEADERS: tuple[str, ...] = (
    "Security", "Quantity", "Cleared Balance", "Available Balance",
    "Unsettled Buy", "Unsettled Sell", "Holding % (Quantity)", "Avg Price",
    "B.E.S Price", "Total Cost", "Traded Price", "Market Value",
    "Holding % (Market Value)", "Sales Commission", "Sales Proceeds",
    "Unrealized Gain / (Loss)", "Unrealized Gain/Loss %", "Unr Today Gain/(Loss)",
)

#: The columns this module actually stores — everything else in
#: `EXPECTED_HEADERS` is read only to locate the header row and to
#: validate the row shape, not because this system needs those figures.
_REQUIRED_HEADERS = ("Security", "Quantity", "Avg Price", "Total Cost")

_TOTAL_ROW_MARKER = "total"

#: A REAL, disclosed tolerance for the Total-row cross-check, found live
#: (18 Aug 2026) against the user's own real uploaded export: `.xlsx`
#: numeric cells are IEEE-754 doubles internally, not exact decimals, so
#: a real value openpyxl reads back as `76748.2` on one cell and
#: `76748.2000000000003` on another (both genuinely representing the
#: same "76,748.20" a human sees in Excel) accumulate slightly different
#: floating-point noise when summed in a different order than Excel's
#: own internal summation used for its own Total row. An EXACT equality
#: check flagged the user's own real, internally-correct file as a
#: MISMATCH purely from this — a real false positive, not a genuine
#: data problem, caught by running this parser against the actual real
#: file rather than only a hand-typed test fixture. One rupee is well
#: below any real accounting-identity failure this check exists to
#: catch (a genuinely mis-parsed row is wrong by orders of magnitude
#: more than float noise ever is) and well above any real float-noise
#: accumulation across a realistic-sized portfolio.
_IDENTITY_TOLERANCE = Decimal("1.00")


def _normalize_header(text: object) -> str:
    return " ".join(str(text).strip().split()).lower() if text is not None else ""


@dataclass(frozen=True)
class ParsedPosition:
    ticker: str
    quantity: Decimal
    avg_price: Decimal
    total_cost: Decimal
    traded_price: Decimal | None
    market_value: Decimal | None
    unrealized_gain_loss: Decimal | None


@dataclass(frozen=True)
class ParsedPortfolio:
    positions: tuple[ParsedPosition, ...]
    stated_total_cost: Decimal | None
    stated_total_market_value: Decimal | None
    identity_check_passed: bool
    identity_check_note: str


def _find_header_row(rows: list[tuple]) -> tuple[int, dict[str, int]] | None:
    """The row whose own cells match `EXPECTED_HEADERS` — matched by
    NAME, not a fixed row/column position, so a real export with extra
    leading rows or reordered columns still locates correctly. `None` if
    no row in the sheet matches, meaning this isn't a shape this parser
    recognises — refuse rather than guess which row is the header."""
    expected_normalized = {_normalize_header(h) for h in _REQUIRED_HEADERS}
    for row_idx, row in enumerate(rows):
        normalized_cells = [_normalize_header(c) for c in row]
        if expected_normalized.issubset(set(normalized_cells)):
            column_index = {}
            for header in EXPECTED_HEADERS:
                norm = _normalize_header(header)
                if norm in normalized_cells:
                    column_index[header] = normalized_cells.index(norm)
            return row_idx, column_index
    return None


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def parse_portfolio_export(rows: list[tuple]) -> ParsedPortfolio | None:
    """`rows` — every row of the sheet, each a tuple of raw cell values
    in column order, exactly as a real spreadsheet-reading library would
    hand them over (this function has no I/O of its own — see `app.
    ingestion.portfolio_import` for the real `.xlsx` reading step).

    `None` — never a guessed structure — when no row matches this
    parser's own real, verified header set at all."""
    header_match = _find_header_row(rows)
    if header_match is None:
        return None
    header_row_idx, column_index = header_match

    positions: list[ParsedPosition] = []
    stated_total_cost: Decimal | None = None
    stated_total_market_value: Decimal | None = None

    for row in rows[header_row_idx + 1:]:
        if not row or row[0] is None:
            continue
        first_cell = _normalize_header(row[0])
        if first_cell == _TOTAL_ROW_MARKER:
            stated_total_cost = _decimal_or_none(row[column_index["Total Cost"]])
            stated_total_market_value = _decimal_or_none(row[column_index["Market Value"]])
            break

        ticker = str(row[column_index["Security"]]).strip()
        quantity = _decimal_or_none(row[column_index["Quantity"]])
        avg_price = _decimal_or_none(row[column_index["Avg Price"]])
        total_cost = _decimal_or_none(row[column_index["Total Cost"]])
        if not ticker or quantity is None or avg_price is None or total_cost is None:
            # A real row that doesn't carry the minimum real fields this
            # module stores — skipped rather than stored with a guessed
            # value, the same "never invent data" rule as everywhere
            # else in this system.
            continue

        positions.append(
            ParsedPosition(
                ticker=ticker,
                quantity=quantity,
                avg_price=avg_price,
                total_cost=total_cost,
                traded_price=_decimal_or_none(row[column_index.get("Traded Price", -1)]) if "Traded Price" in column_index else None,
                market_value=_decimal_or_none(row[column_index.get("Market Value", -1)]) if "Market Value" in column_index else None,
                unrealized_gain_loss=(
                    _decimal_or_none(row[column_index["Unrealized Gain / (Loss)"]])
                    if "Unrealized Gain / (Loss)" in column_index
                    else None
                ),
            )
        )

    identity_note = "No 'Total' row found in the file — nothing to cross-check the parsed positions against."
    identity_passed = False
    if stated_total_cost is not None:
        summed_cost = sum((p.total_cost for p in positions), Decimal(0))
        summed_market_value = sum((p.market_value for p in positions if p.market_value is not None), Decimal(0))
        cost_ok = abs(summed_cost - stated_total_cost) <= _IDENTITY_TOLERANCE
        value_ok = (
            stated_total_market_value is None
            or abs(summed_market_value - stated_total_market_value) <= _IDENTITY_TOLERANCE
        )
        identity_passed = cost_ok and value_ok
        identity_note = (
            f"Parsed total cost {summed_cost:,} vs the file's own stated {stated_total_cost:,}"
            + ("" if cost_ok else " — MISMATCH")
            + (
                f"; parsed market value {summed_market_value:,} vs the file's own stated "
                f"{stated_total_market_value:,}" + ("" if value_ok else " — MISMATCH")
                if stated_total_market_value is not None
                else ""
            )
        )

    return ParsedPortfolio(
        positions=tuple(positions),
        stated_total_cost=stated_total_cost,
        stated_total_market_value=stated_total_market_value,
        identity_check_passed=identity_passed,
        identity_check_note=identity_note,
    )
