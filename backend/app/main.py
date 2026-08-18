from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    corporate_actions,
    data_health,
    fundamentals,
    health,
    market,
    national_projects,
    portfolio,
    securities,
    valuation,
)
from app.config import settings

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="CSE Alpha Engine",
    description=(
        "Decision-support API for CSE equities. Deterministic code computes; "
        "AI explains. This service never places an order and never exposes a "
        "single-verdict recommendation endpoint — see Design Law 6, Master "
        "Spec §4."
    ),
    version="0.1.0-phase1",
)

# Confirm-queue frontend (frontend/) runs on the Vite dev server during
# development. This is an internal review tool, not a public API — origins
# are limited to local dev ports, never a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
app.include_router(securities.router)
app.include_router(market.router)
app.include_router(corporate_actions.router)
app.include_router(fundamentals.router)
app.include_router(data_health.router)
app.include_router(valuation.router)
app.include_router(national_projects.router)
app.include_router(portfolio.router)
