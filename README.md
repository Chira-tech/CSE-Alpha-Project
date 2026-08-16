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

There is a **runnable web app** — see Quick start below. It shows real CSE
data (live index levels, all ~283 listed companies, prices, the review
queues, data health). It deliberately does **not** show fair values,
scores or buy prices, because the engines that compute them are Phase 2–3
and haven't been built: the company file lists those gaps explicitly
rather than rendering a placeholder number, which the UI specification
forbids outright.

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
frontend/            React + TypeScript confirm-queue tool (see frontend/README.md) —
                      NOT the Phase 2+ product frontend, just enough UI to review and
                      approve the ingestion drafts Phase 1 produces
```

## Quick start — run it and look at it

Two terminals. Backend first:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate                       # Windows
pip install -r requirements.txt

# Dev mode: SQLite, no external database needed.
set DATABASE_URL=sqlite+pysqlite:///./devdb.sqlite   # Windows (use `export` on macOS/Linux)
alembic upgrade head

# Pull the real universe + latest prices from the live CSE API (~1 request)
python -m app.cli bootstrap

uvicorn app.main:app --reload
```

Then the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. You'll get four screens: Market (live ASPI
and sector indices), Companies (all ~283 listed names, searchable, click
through to a company file), Review queue, and Data health.

### A note on SQLite vs PostgreSQL

Master Spec §51 specifies PostgreSQL + TimescaleDB, and that remains the
production target — the price series will want hypertables long before
this is running at scale. SQLite is supported purely so the app is
runnable on a clean machine with nothing installed; the migrations detect
the missing Timescale extension and fall back to a plain table
automatically. Point `DATABASE_URL` at Postgres and the same migrations
apply unchanged.

### Optional: populate the review queues

The Review screen is empty until ingestion has scraped something. Corporate
actions are rate-limited to >=2s per request (§5), so the full sweep of
283 companies takes 10+ minutes — start with a few:

```bash
python -m app.cli ingest-corporate-actions --limit 5
```

## Why start here and not with a model

Master Spec §54 and the failure-mode register (Part N, #1) are explicit:
almost every backtest failure on the CSE traces back to look-ahead bias from
restated financials or unadjusted corporate actions. Building a valuation
model on top of a data layer that doesn't yet enforce point-in-time queries
and total-return adjustment would produce numbers that are precise and wrong.
Phase 1 has no user-visible payoff by itself; it is the moat (§0, "the five
things that make this work").
