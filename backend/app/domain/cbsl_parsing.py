"""
Parser for CBSL's "Daily Economic Indicators" PDF.

This is the source for most of §29's variable set — T-bill yields across
the curve, the policy rate, SRR, AWPR, CCPI/NCPI inflation, exchange
rates — published daily and archived back to 2013 at a completely
predictable URL:

    https://www.cbsl.gov.lk/sites/default/files/daily_economic_indicators_YYYYMMDD_e.pdf

WHY COORDINATES AND NOT TEXT. The PDF is a dashboard: several unrelated
panels laid out side by side. `extract_text()` interleaves them, so the
T-bill values arrive as a bare run of "9.44 9.44 / 9.78 9.75 / 10.01
10.01" separated from the "91 Day / 182 Day / 364 Day" labels by an
unrelated chart's axis labels. Reading that stream positionally would be
guesswork. Every value below is instead anchored to its own label by
row (`top`) and assigned to a column by x-position against the panel's
own "Primary Market" / "Secondary Market" headers.

TWO DISTINCTIONS THAT MATTER, both easy to get silently wrong:

  1. PRIMARY vs SECONDARY market. The T-bill panel shows both, in
     adjacent columns, and they differ (9.78 vs 9.75 on the 182-day the
     day this was written). §17.2 specifies "364-day T-bill primary
     auction yield" and §35.1 "91-day T-bill weekly primary market
     yield" — the primary column. Both are captured, under distinct
     series ids, so nothing has to guess later.

  2. OBSERVATION DATE vs PUBLICATION DATE. The 13 August edition carries
     a footer reading "Published on 14-Aug-2026", and its two T-bill
     columns are themselves dated (12 Aug primary, 13 Aug secondary). So
     a figure observed on the 12th did not become public until the 14th.
     §6 turns on exactly this gap, so the parser returns both dates per
     observation and never conflates them.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import io
import re
from decimal import Decimal, InvalidOperation

import pdfplumber

# Series ids, namespaced by origin to match app.domain.macro's convention.
SERIES_TBILL_91D = "cbsl.tbill_91d"
SERIES_TBILL_182D = "cbsl.tbill_182d"
SERIES_TBILL_364D = "cbsl.tbill_364d"
SERIES_TBILL_91D_SECONDARY = "cbsl.tbill_91d_secondary"
SERIES_TBILL_182D_SECONDARY = "cbsl.tbill_182d_secondary"
SERIES_TBILL_364D_SECONDARY = "cbsl.tbill_364d_secondary"
SERIES_POLICY_RATE = "cbsl.policy_rate"
SERIES_SRR = "cbsl.srr"
SERIES_AWPR = "cbsl.awpr"
SERIES_AWCMR = "cbsl.awcmr"
SERIES_CCPI_YOY = "cbsl.ccpi_yoy"
SERIES_NCPI_YOY = "cbsl.ncpi_yoy"
SERIES_USD_LKR_BUY = "cbsl.usd_lkr_tt_buying"
SERIES_USD_LKR_SELL = "cbsl.usd_lkr_tt_selling"

_TENOR_SERIES = {
    "91": (SERIES_TBILL_91D, SERIES_TBILL_91D_SECONDARY),
    "182": (SERIES_TBILL_182D, SERIES_TBILL_182D_SECONDARY),
    "364": (SERIES_TBILL_364D, SERIES_TBILL_364D_SECONDARY),
}

_DATE_RE = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{2}$")
_PUBLISHED_RE = re.compile(r"Published on\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", re.I)
_NUMBER_RE = re.compile(r"^-?[\d,]+\.?\d*%?$")
#: CBSL glues the reference period to its value: "July" + "7.3%" is
#: emitted as the single token "20267.3%", and "2026Q1" + "5.1%" as
#: "2026Q15.1%". The optional leading year (and quarter) must be consumed
#: explicitly — a greedy `(\d+\.\d+)%` reads "20267.3" and yields a CCPI
#: of 202%, which is what this pattern originally did.
_TRAILING_PCT_RE = re.compile(r"^(?:\d{4}(?:Q\d)?)?(\d{1,3}\.\d+)%$")

#: Sanity band for anything stored as a rate fraction. Sri Lankan
#: inflation peaked near 70% in 2022 and policy rates near 16%, so this
#: is deliberately wide — it is a guard against unit and parsing errors
#: (a 202% CCPI, a rate stored as 10.01 instead of 0.1001), not an
#: economic judgement about plausible values.
_RATE_MIN = Decimal("-0.50")
_RATE_MAX = Decimal("1.50")


class CbslParseError(RuntimeError):
    """Raised when the PDF's structure isn't what this parser expects.

    Deliberately loud: a silently-empty result would let the risk-free
    rate quietly go stale, and §17.2's cost of equity is built on it.
    """


@dataclasses.dataclass(frozen=True)
class CbslObservation:
    series_id: str
    obs_date: dt.date
    first_available_date: dt.date
    value: Decimal
    note: str = ""


@dataclasses.dataclass(frozen=True)
class CbslDailyIndicators:
    edition_date: dt.date
    published_date: dt.date
    observations: tuple[CbslObservation, ...]

    def by_series(self, series_id: str) -> CbslObservation | None:
        return next((o for o in self.observations if o.series_id == series_id), None)


def _parse_short_date(text: str, century: int = 2000) -> dt.date | None:
    """"13-Aug-26" -> date(2026, 8, 13)."""
    try:
        parsed = dt.datetime.strptime(text.strip(), "%d-%b-%y").date()
    except ValueError:
        return None
    return parsed


def _parse_long_date(text: str) -> dt.date | None:
    """"14-Aug-2026" -> date(2026, 8, 14)."""
    try:
        return dt.datetime.strptime(text.strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _to_decimal(token: str) -> Decimal | None:
    token = token.strip().rstrip("%").replace(",", "")
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def _as_fraction(value: Decimal, *, label: str) -> Decimal:
    """CBSL prints rates as percentages (10.01, 8.75%). Everything in this
    system stores rates as decimal fractions so the earnings yield, the
    T-bill yield and the spread share units — see app.domain.macro.

    Guarded, because the two ways this goes wrong both produce a number
    that renders perfectly happily: a parse error that swallows a year
    prefix, and a value that was already a fraction being divided again.
    Neither is detectable downstream, and both would flow straight into
    the cost of equity.
    """
    fraction = value / 100
    if not (_RATE_MIN <= fraction <= _RATE_MAX):
        raise CbslParseError(
            f"{label}: parsed {value} -> {fraction} as a fraction, outside the sanity band "
            f"[{_RATE_MIN}, {_RATE_MAX}]. This is almost certainly a parsing or unit error, "
            "not a real rate."
        )
    return fraction


def _row(words: list[dict], top: float, tol: float = 6.0) -> list[dict]:
    return sorted((w for w in words if abs(w["top"] - top) < tol), key=lambda w: w["x0"])


def _find(words: list[dict], text: str) -> dict | None:
    return next((w for w in words if w["text"] == text), None)


def _centre(word: dict) -> float:
    return (word["x0"] + word["x1"]) / 2


def _parse_tbills(
    words: list[dict], published: dt.date, fallback_obs: dt.date
) -> list[CbslObservation]:
    """The T-bill panel: three tenor rows, two market columns.

    Column assignment is by x-distance to the panel's own "Primary
    Market" / "Secondary Market" headers rather than by assuming
    left-is-primary, so a layout change surfaces as a parse failure
    instead of silently swapping the two.
    """
    primary_hdr = _find(words, "Primary")
    secondary_hdr = _find(words, "Secondary")
    if primary_hdr is None or secondary_hdr is None:
        raise CbslParseError("could not locate the Primary/Secondary market headers")

    # Columns are assigned by ORDER, not by nearest-centre distance.
    #
    # Distance was the first approach and it is genuinely fragile here:
    # the "Primary Market" label sits left of its own value column, so on
    # the real page the 9.44 under Primary was only ~3pt closer to the
    # Primary label than to the Secondary one. That margin depends on
    # glyph widths, and a fixture with slightly different widths flipped
    # every value to the wrong column. Left-of-right ordering is exact and
    # carries no such margin.
    columns_left_to_right = (
        ("primary", "secondary")
        if primary_hdr["x0"] <= secondary_hdr["x0"]
        else ("secondary", "primary")
    )

    # Each column carries its own date header, on the row between the
    # market labels and the first tenor row. Same ordering logic.
    date_headers = sorted(
        (
            w
            for w in words
            if _DATE_RE.match(w["text"])
            and primary_hdr["top"] < w["top"] < primary_hdr["top"] + 30
            and _parse_short_date(w["text"]) is not None
        ),
        key=lambda w: w["x0"],
    )
    col_dates: dict[str, dt.date] = {}
    for column, header in zip(columns_left_to_right, date_headers):
        parsed = _parse_short_date(header["text"])
        if parsed is not None:
            col_dates[column] = parsed

    observations: list[CbslObservation] = []
    for tenor, (primary_series, secondary_series) in _TENOR_SERIES.items():
        label = next(
            (
                w
                for w in words
                if w["text"] == tenor
                and any(
                    n["text"] == "Day"
                    and abs(n["top"] - w["top"]) < 4
                    # Lower bound is negative on purpose: pdfplumber's word
                    # boxes for "364" and "Day" overlap by ~1.5pt in this
                    # PDF, so requiring a positive gap finds nothing.
                    and -4 < n["x0"] - w["x1"] < 12
                    for n in words
                )
            ),
            None,
        )
        if label is None:
            continue

        values = [
            w
            for w in _row(words, label["top"])
            if w["x0"] > label["x1"] and _NUMBER_RE.match(w["text"]) and _to_decimal(w["text"]) is not None
        ]
        # `values` is already sorted left-to-right by _row(), so the nth
        # value belongs to the nth column. A row with more values than
        # columns means the layout isn't what we think it is, and
        # guessing would put a real number under the wrong series.
        if len(values) > len(columns_left_to_right):
            raise CbslParseError(
                f"{tenor}-day row has {len(values)} values but the panel has "
                f"{len(columns_left_to_right)} columns — layout has changed"
            )

        for column, w in zip(columns_left_to_right, values):
            raw = _to_decimal(w["text"])
            if raw is None:
                continue
            observations.append(
                CbslObservation(
                    series_id=primary_series if column == "primary" else secondary_series,
                    obs_date=col_dates.get(column, fallback_obs),
                    first_available_date=published,
                    value=_as_fraction(raw, label=f"{tenor}-day T-bill ({column})"),
                    note=f"{tenor}-day T-bill, {column} market",
                )
            )

    if not observations:
        raise CbslParseError("found the T-bill panel but extracted no yields")
    return observations


def _labelled_percent(
    words: list[dict], label_text: str, series_id: str, published: dt.date, obs_date: dt.date, note: str
) -> CbslObservation | None:
    """A scalar printed immediately to the right of its label on the same
    row, e.g. 'SRR: 2.00%'."""
    label = _find(words, label_text)
    if label is None:
        return None
    for w in _row(words, label["top"]):
        if w["x0"] <= label["x1"]:
            continue
        value = _to_decimal(w["text"])
        if value is not None and w["text"].endswith("%"):
            return CbslObservation(
                series_id=series_id,
                obs_date=obs_date,
                first_available_date=published,
                value=_as_fraction(value, label=note),
                note=note,
            )
    return None


def _glued_percent(
    words: list[dict], anchor: str, series_id: str, published: dt.date, obs_date: dt.date, note: str
) -> CbslObservation | None:
    """CBSL glues a period label to its value — "July" + "7.3%" is emitted
    as the single token "20267.3%". Pull the trailing percentage off the
    right-hand end rather than trying to split the period out."""
    label = _find(words, anchor)
    if label is None:
        return None
    for w in _row(words, label["top"]):
        if w["x0"] <= label["x1"]:
            continue
        match = _TRAILING_PCT_RE.search(w["text"])
        if match:
            value = _to_decimal(match.group(1))
            if value is not None:
                return CbslObservation(
                    series_id=series_id,
                    obs_date=obs_date,
                    first_available_date=published,
                    value=_as_fraction(value, label=note),
                    note=note,
                )
    return None


def _usd_rates(
    words: list[dict], published: dt.date, obs_date: dt.date
) -> list[CbslObservation]:
    label = _find(words, "USD")
    if label is None:
        return []
    numbers = [
        w for w in _row(words, label["top"]) if w["x0"] > label["x1"] and _to_decimal(w["text"]) is not None
    ]
    out: list[CbslObservation] = []
    # TT Buying then TT Selling, left to right per the panel header.
    for series_id, word, note in zip(
        (SERIES_USD_LKR_BUY, SERIES_USD_LKR_SELL), numbers, ("TT buying", "TT selling")
    ):
        value = _to_decimal(word["text"])
        if value is not None:
            out.append(
                CbslObservation(
                    series_id=series_id,
                    obs_date=obs_date,
                    first_available_date=published,
                    value=value,  # a price, not a rate — no /100
                    note=f"USD/LKR {note}",
                )
            )
    return out


def parse_daily_indicators(pdf_bytes: bytes, edition_date: dt.date) -> CbslDailyIndicators:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if not pdf.pages:
            raise CbslParseError("PDF has no pages")
        page = pdf.pages[0]
        words = page.extract_words()
        text = page.extract_text() or ""

    if not words:
        raise CbslParseError("no extractable text — the PDF may be a scanned image")

    # "Published on 14-Aug-2026" in the footer. Falls back to the edition
    # date, which is conservative in the wrong direction (it would make
    # data look available a day earlier than it was), so a missing footer
    # is worth surfacing rather than silently accepting.
    published_match = _PUBLISHED_RE.search(text)
    published = _parse_long_date(published_match.group(1)) if published_match else None
    if published is None:
        raise CbslParseError(
            "could not find the 'Published on' date — refusing to guess, because "
            "first_available_date is what keeps point-in-time queries honest (§6)"
        )

    observations: list[CbslObservation] = list(_parse_tbills(words, published, edition_date))

    for label, series_id, note in (
        ("(OPR):", SERIES_POLICY_RATE, "Overnight Policy Rate"),
        ("SRR:", SERIES_SRR, "Statutory Reserve Ratio"),
        ("AWPR:", SERIES_AWPR, "Weekly AWPR"),
    ):
        observation = _labelled_percent(words, label, series_id, published, edition_date, note)
        if observation is not None:
            observations.append(observation)

    for anchor, series_id, note in (
        ("NCPI", SERIES_NCPI_YOY, "NCPI year-on-year"),
        ("CCPI", SERIES_CCPI_YOY, "CCPI year-on-year"),
    ):
        observation = _glued_percent(words, anchor, series_id, published, edition_date, note)
        if observation is not None:
            observations.append(observation)

    observations.extend(_usd_rates(words, published, edition_date))

    return CbslDailyIndicators(
        edition_date=edition_date,
        published_date=published,
        observations=tuple(observations),
    )


def edition_url(edition_date: dt.date) -> str:
    """The archive URL pattern, verified back to 2013."""
    return (
        "https://www.cbsl.gov.lk/sites/default/files/"
        f"daily_economic_indicators_{edition_date:%Y%m%d}_e.pdf"
    )
