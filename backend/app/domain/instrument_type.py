"""
What kind of instrument a CSE ticker actually is, and who issued it.

The CSE encodes both in the symbol: `COMB.N0000` and `COMB.X0000` are the
voting and non-voting lines of one bank. The exchange's own ISINs agree —
`LK0053N00005` and `LK0053X00004` share a base and differ by the same
letter — so this is the exchange's convention, not a pattern read into it.

WHY THIS EXISTS. The universe comes from `tradeSummary`, which returns
every line that traded, not every company. Of the 283 lines it returned on
17 Aug 2026, 262 were ordinary shares and the rest were not:

    18 non-voting lines  (COMB.X0000, HNB.X0000, SEYB.X0000, NTB.X0000, ...)
     2 closed-end fund units (CALC.U0000, CALU.U0000)
     1 rights line       (AAF.R0000)

Treating those as 21 more companies is wrong in three separate ways:

  1. DOUBLE COUNTING THE ISSUER. Commercial Bank appears twice. A screen
     shows it twice, and — worse — the §27.1/§39.1 concentration caps
     (10%/6%/3% by tier) count two lines of one bank as two positions, so
     a cap meant to limit single-issuer exposure is quietly evaded.
  2. FUNDAMENTALS BELONG TO THE ISSUER, NOT THE LINE. Commercial Bank
     files one set of statements. One ROE, one book value, shared by both
     lines. Keyed per ticker, the fundamentals either get duplicated or
     one line silently has none.
  3. SOME LINES ARE NOT EQUITY AT ALL. A rights line is a temporary
     instrument that expires; a closed-end fund unit is a fund. Neither
     has earnings or book value, so a P/E or an ROE computed for them is
     not merely imprecise, it is meaningless — and it would rank.

Verified live against `companyInfoSummery`: COMB.X0000 has 97,325,945
shares issued and COMB.N0000 has 1,556,530,602, both under the name
COMMERCIAL BANK OF CEYLON PLC.
"""
from __future__ import annotations

import enum
import re

_SUFFIX_RE = re.compile(r"^(?P<issuer>[A-Z0-9]+)\.(?P<kind>[A-Z])(?P<serial>\d{4})$")


class InstrumentType(str, enum.Enum):
    ORDINARY = "ordinary"
    """`.N` — ordinary voting shares. The default equity line."""

    NON_VOTING = "non_voting"
    """`.X` — non-voting ordinary shares. Genuine equity in the same
    company, and on the CSE often liquid (COMB.X, HNB.X, SEYB.X), so it is
    NOT excluded — but it shares an issuer with the `.N` line and must be
    grouped with it rather than counted separately."""

    PREFERENCE = "preference"
    """`.P` — preference shares. Excluded from equity valuation: a fixed
    dividend with no participation in growth is not what a DDM or FCFE
    anchor (§24) is modelling, so a "fair value" for one would be a
    category error rather than a bad estimate."""

    DEBENTURE = "debenture"
    """`.D` — listed debt. Bank of Ceylon appears on the exchange only as
    BOC.D0000 for exactly this reason: it is a debt issuer, not a listed
    equity."""

    RIGHTS = "rights"
    """`.R` — a tradeable right, which expires. Not a company."""

    UNIT = "unit"
    """`.U` — closed-end fund or unit trust units. A fund, not an
    operating business."""

    WARRANT = "warrant"
    """`.W` — warrants. A derivative claim, not equity."""

    UNKNOWN = "unknown"
    """No suffix, or a letter not seen before. Four such codes exist
    (AFIN, MIFL, SIC, SLFL); `companyInfoSummery` returns no shares
    issued, no par value and no ISIN for them, so they are not tradeable
    equity lines. Deliberately NOT folded into ORDINARY — an unrecognised
    code must never default into the investable universe."""


_BY_LETTER = {
    "N": InstrumentType.ORDINARY,
    "X": InstrumentType.NON_VOTING,
    "P": InstrumentType.PREFERENCE,
    "D": InstrumentType.DEBENTURE,
    "R": InstrumentType.RIGHTS,
    "U": InstrumentType.UNIT,
    "W": InstrumentType.WARRANT,
}

# Common equity — the only instruments a valuation model may be pointed
# at. Everything else is either debt, a derivative, a fund or a wrapper.
COMMON_EQUITY = frozenset({InstrumentType.ORDINARY, InstrumentType.NON_VOTING})


def classify(symbol: str) -> InstrumentType:
    """Classify a CSE symbol by its suffix.

    Unrecognised shapes return UNKNOWN rather than guessing ORDINARY.
    Defaulting the other way would put debentures and expiring rights into
    the equity universe the moment the exchange adds a letter.
    """
    match = _SUFFIX_RE.match(symbol.strip().upper())
    if match is None:
        return InstrumentType.UNKNOWN
    return _BY_LETTER.get(match.group("kind"), InstrumentType.UNKNOWN)


def issuer_code(symbol: str) -> str:
    """The issuer stem shared by every line of one company.

    `COMB.N0000` and `COMB.X0000` both return `COMB`, which is what lets
    fundamentals attach once and concentration limits count one bank once.
    A symbol with no suffix is its own issuer.
    """
    symbol = symbol.strip().upper()
    match = _SUFFIX_RE.match(symbol)
    return match.group("issuer") if match else symbol


def is_common_equity(symbol: str) -> bool:
    return classify(symbol) in COMMON_EQUITY


def is_primary_line(symbol: str) -> bool:
    """Whether this is the issuer's main voting line.

    Used to pick one row per company for a screen. Non-voting lines are
    still investable — they are simply not the row a company-level view
    should lead with.
    """
    return classify(symbol) is InstrumentType.ORDINARY
