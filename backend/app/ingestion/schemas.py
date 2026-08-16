"""
Pydantic response schemas for cse.lk endpoints.

IMPORTANT — read before trusting these: the endpoint paths and field names
below are transcribed from Master Spec Part II §5.2, which itself describes
them as "reverse-engineered rather than officially documented." They have
NOT been verified against the live API in this session (no network access
during the build). Treat every field here as a hypothesis to confirm on
first real integration, per ROADMAP.md. The point of validating against a
schema at all — even an unverified one — is that the *first* real call will
either confirm it or raise ShapeChangedError loudly instead of the loader
silently reading `None` out of a renamed field forever.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Lenient(BaseModel):
    """Ignore unknown fields (the API is undocumented and may add fields
    harmlessly) but still fail if a field we depend on is missing or of the
    wrong type."""

    model_config = ConfigDict(extra="ignore")


class MarketStatus(_Lenient):
    status: str  # e.g. "Open" | "Closed"


class TodaySharePriceRow(_Lenient):
    symbol: str
    price: float
    change: float | None = None
    changePercentage: float | None = None
    tradeVolume: int | None = None


class TradeSummaryRow(_Lenient):
    symbol: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    turnover: float | None = None
    trades: int | None = None


class CompanyInfoSummary(_Lenient):
    symbol: str
    name: str
    marketCap: float | None = None
    sharesIssued: int | None = None
