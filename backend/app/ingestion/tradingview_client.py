"""
TradingView's public screener API, used as an independent second source
for CSE closing prices (Part II §5.2, PARAMETERS.md #5).

Two hosts matter here, with different rules:

    www.tradingview.com/symbols/...     interactive page, not used here
    scanner.tradingview.com/...         robots.txt: Disallow: /
                                                      Allow: /global/scan

`/symbol?symbol=...` — the endpoint a browser hits when a chart page
loads — is under the blanket Disallow and is deliberately NOT used here.
`/global/scan` is the one path robots.txt explicitly allows: it is
TradingView's own bulk screener API (what tradingview.com/screener/
itself calls), and it happens to also answer a query scoped to an exact
list of symbols, so the one compliant endpoint is also the more efficient
one — a single request covers the whole CSE universe instead of one
request per ticker.

CSE lines map onto TradingView 1:1 with no translation needed: our
ticker `COMB.N0000` is TradingView's `CSELK:COMB.N0000`, verified live.
Unknown symbols are simply absent from the response rather than erroring
per-symbol, so one bad ticker cannot break the batch.
"""
from __future__ import annotations

import logging

import httpx

from app.domain.second_source import SecondSourceQuote

logger = logging.getLogger("cse_alpha.ingestion.tradingview")

_SCAN_URL = "https://scanner.tradingview.com/global/scan"
_EXCHANGE_PREFIX = "CSELK:"
_COLUMNS = ["close", "high", "low", "open", "volume", "currency", "exchange"]

# Conservative and arbitrary in the absence of a published rate limit for
# this endpoint (robots.txt gives none) — one request covers the whole
# universe in practice, so there is no real pacing pressure to trade off
# against politeness.
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_TICKERS_PER_REQUEST = 150


class TradingViewFetchError(RuntimeError):
    """Raised when the response cannot be trusted without guessing."""


def fetch_quotes(
    tickers: list[str], *, client: httpx.Client | None = None
) -> dict[str, SecondSourceQuote]:
    """Fetch quotes for the given CSE tickers, chunked to stay well under
    any implicit payload/URL-length limits. Returns only the tickers
    TradingView actually recognised — a ticker with no CSELK listing on
    TradingView (verified: 26 of our own securities have no GICS
    classification either, and the two gaps are not guaranteed to be the
    same set) is simply absent, not an error.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS)
    quotes: dict[str, SecondSourceQuote] = {}
    try:
        for start in range(0, len(tickers), MAX_TICKERS_PER_REQUEST):
            chunk = tickers[start : start + MAX_TICKERS_PER_REQUEST]
            quotes.update(_fetch_chunk(client, chunk))
    finally:
        if owns_client:
            client.close()
    return quotes


def _fetch_chunk(client: httpx.Client, tickers: list[str]) -> dict[str, SecondSourceQuote]:
    symbols = [f"{_EXCHANGE_PREFIX}{t}" for t in tickers]
    body = {"symbols": {"tickers": symbols, "query": {"types": []}}, "columns": _COLUMNS}

    response = client.post(
        _SCAN_URL,
        json=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    payload = response.json()

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise TradingViewFetchError(f"unexpected /global/scan shape: {type(payload).__name__}")

    quotes: dict[str, SecondSourceQuote] = {}
    for row in rows:
        symbol = row.get("s", "")
        ticker = symbol.removeprefix(_EXCHANGE_PREFIX)
        values = row.get("d")
        if not symbol.startswith(_EXCHANGE_PREFIX) or not isinstance(values, list) or len(values) != len(_COLUMNS):
            logger.warning("skipping unreadable /global/scan row: %r", row)
            continue
        close, high, low, open_, volume, currency, exchange = values
        try:
            quotes[ticker] = SecondSourceQuote(
                close=_dec(close),
                high=_dec(high),
                low=_dec(low),
                open=_dec(open_),
                volume=int(volume) if volume is not None else 0,
                currency=str(currency),
                exchange=str(exchange),
            )
        except (TypeError, ValueError):
            logger.warning("skipping %s: unreadable field values %r", ticker, values)
            continue

    return quotes


def _dec(value: object):
    from decimal import Decimal, InvalidOperation

    if value is None:
        raise ValueError("missing value")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(str(exc)) from exc
