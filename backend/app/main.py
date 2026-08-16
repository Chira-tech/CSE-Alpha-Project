from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes import corporate_actions, fundamentals, health, securities
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

app.include_router(health.router)
app.include_router(securities.router)
app.include_router(corporate_actions.router)
app.include_router(fundamentals.router)
