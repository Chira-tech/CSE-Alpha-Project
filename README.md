# CSE Alpha Engine

An automated equity research, valuation and decision-support platform for the
Colombo Stock Exchange. See `/docs` (the four spec PDFs) for the full design:

- `CSE Alpha Engine - Master Specification v2.0.pdf` — the authoritative spec.
  Supersedes the Architecture and Part II documents, which are kept for
  historical context only.
- `CSE Alpha Engine - UI and Experience Specification v1.0.pdf` — design
  system and screen specs for the frontend.

**Design principle:** arithmetic is deterministic code; AI interprets,
narrates and proposes. It never computes a valuation and never places an
order. There is no BUY button anywhere in this product.

## Status

Build follows the phased sequence in Master Spec §54. We are in **Phase 1 —
point-in-time data spine**.

| Phase | Deliverable | Status |
|---|---|---|
| 1 | PIT data spine, cse.lk ingestion, corporate actions, reconciliation, coverage tiers, provenance model | 🔨 in progress |
| 2 | Fundamental engine, trend detection, sector routing, integrity veto, screener UI | not started |
| 3 | Valuation engine, price ladder, margin-of-safety engine | not started |
| 4 | Scheduler, always-on service, alerting, decision capture | not started |
| 5 | Macro engine (ARDL, regime classifier, sector sensitivity) | not started |
| 6 | Factor library, Carhart certification, timing engine, fusion | not started |
| 7 | AI research writer + agent Tier A | not started |
| 8 | Portfolio, thesis-drift monitor, backtest lab, monitoring | not started |
| 9 | Agent Tier B/C | not started |

See `ROADMAP.md` for the detailed phase-1 task list and `PARAMETERS.md` for
the open-parameter decisions (Master Spec Part O) that were defaulted so the
build could start — **review these**, they materially change thresholds
downstream.

## Repository layout

```
backend/            Python service: ingestion, domain logic, API, jobs
  app/
    config.py        Settings (env-driven)
    db/               SQLAlchemy engine/session, declarative base
    models/           Core schema (Master Spec §9), one module per table group
    domain/           Pure deterministic logic: corporate actions math,
                      coverage gates, provenance rules — no I/O, fully unit
                      tested, this is the part that must never be "roughly right"
    ingestion/        cse.lk client (rate-limited, circuit-broken, schema-
                      validated) and per-domain loaders
    jobs/             Scheduled jobs: EOD snapshot, reconciliation, etc.
    api/              FastAPI routes
  alembic/            DB migrations
  tests/
frontend/            React + Tailwind (design tokens from the UI spec) — later phase
```

## Getting started (backend)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
copy .env.example .env       # then fill in DB URL etc.
alembic upgrade head
uvicorn app.main:app --reload
```

Requires PostgreSQL with the TimescaleDB extension (Master Spec §51). For
local dev without Timescale installed, the hypertable creation step in the
migration is skipped automatically (see `alembic/env.py`) and plain Postgres
tables are used — fine for correctness testing, not for production price-series
performance.

## Why start here and not with a model

Master Spec §54 and the failure-mode register (Part N, #1) are explicit:
almost every backtest failure on the CSE traces back to look-ahead bias from
restated financials or unadjusted corporate actions. Building a valuation
model on top of a data layer that doesn't yet enforce point-in-time queries
and total-return adjustment would produce numbers that are precise and wrong.
Phase 1 has no user-visible payoff by itself; it is the moat (§0, "the five
things that make this work").
