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

Build follows the phased sequence in Master Spec §54. Phases 1-3's
engines are built (data spine, fundamentals/trend/routing, and now the
full valuation math — DCF through the price ladder); Phase 4 (scheduler
hardening, alerting, decision capture UI) has not started.

There is a **runnable web app** — see Quick start below. It shows real CSE
data (live index levels, all 283 listed lines from 264 issuers, prices, the review
queues, data health). It deliberately does **not** show fair values,
scores or buy prices: the Phase 3 valuation engines exist now and are
unit-tested against hand-worked reference cases (`backend/app/domain/
dcf.py` through `price_ladder.py`), but nothing wires them to a real
company's live data or renders them in the UI yet — see ROADMAP.md's
Phase 3 section for exactly which two models (residual income, justified
P/B) are already wireable and which are still blocked on unextracted
data (DCF, DDM, SOTP, asset-based). Until that wiring and a screener/
valuation UI exist, the company file lists the gap explicitly rather than
rendering a placeholder number, which the UI specification forbids
outright.

| Phase | Deliverable | Status |
|---|---|---|
| 1 | PIT data spine, cse.lk ingestion, corporate actions, reconciliation, coverage tiers, provenance model | 🔨 in progress |
| 2 | Fundamental engine, trend detection, sector routing, integrity veto, screener UI | 🔨 ratio engine + trend detection (§13) + model router (§15/§16) built; integrity veto (§14) blocked on unextracted data; screener UI not started |
| 3 | Valuation engine, price ladder, margin-of-safety engine | ✅ math built and tested (§17-26: cost of equity, DCF, DDM, residual income, relative valuation, SOTP, asset-based, scenarios, triangulation, margin of safety, price ladder); not yet wired to live per-company data end-to-end or exposed in the UI |
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
and sector indices), Companies (all 283 listed lines, searchable, click
through to a company file), Review queue, and Data health.

### A note on SQLite vs PostgreSQL

Master Spec §51 specifies PostgreSQL + TimescaleDB, and that remains the
production target — the price series will want hypertables long before
this is running at scale. SQLite is supported purely so the app is
runnable on a clean machine with nothing installed; the migrations detect
the missing Timescale extension and fall back to a plain table
automatically. Point `DATABASE_URL` at Postgres and the same migrations
apply unchanged.

### Keeping data collection running

Forward capture at the close is still how a day's own price gets in, and
a day the worker was down for is still gone — `companyChartDataByStock`
(below) repairs gaps within the trailing ~year, not beyond it. Run the
worker alongside the API:

```bash
python -m app.worker
```

It holds the §52 schedule — EOD snapshot 15:00 Colombo, reconciliation
15:05, corporate-actions scan 16:00, financial-statement scan 16:30
weekdays, plus Saturday's issuer-registry / sector / price-gap-repair
jobs — and otherwise idles. All times are anchored to the exchange's
clock regardless of where the host machine is.

### Backfilling ~1 year of per-company price history

```bash
python -m app.cli backfill-prices          # all ~283 lines, ~10 min at CSE pacing
```

Fills gaps only — a date already captured live at the close is never
touched, and today's still-forming session is always skipped. Also runs
automatically every Saturday. This is still a single-source (cse.lk)
series; see PARAMETERS.md #5 for what it does and doesn't solve.

### Backfilling financial-statement history

```bash
python -m app.cli backfill-financials --ticker COMB.N0000   # one company: 75+ requests, minutes
python -m app.cli backfill-financials --limit 5              # a handful, for a first run
python -m app.cli backfill-financials                        # every company — genuinely long; not scheduled
```

Per-company annual and quarterly filings back to 2012, catalogued —
`getFinancialAnnouncement` (the daily scheduled scan) only ever sees the
single most recent filing platform-wide. Only files from roughly 2019
onward actually download (older ones 403 from the CDN despite being
listed); the command reports `unavailable` separately from genuine
failures. Everything lands in the confirm queue exactly like the daily
scan — nothing here skips human confirmation (§8). Not scheduled: a
single well-documented company is 75+ paced requests on its own, and a
weekly sweep of the whole exchange would be a genuinely heavy load on an
unofficial endpoint (§5).

### Checking a real fair value (§18-26, wired to live data)

```
GET /valuation/{ticker}
```

Runs the full Phase 3 pipeline for one company: archetype routing, the
two valuation models that don't need still-unextracted data (justified
P/B and residual income, §20.2/§19.3), triangulation, margin of safety,
and the price ladder. Open `http://localhost:8000/docs` and try it
against a ticker with a confirmed fundamentals period — most tickers
don't have one yet (§8: an AI-assisted extraction must be human-
confirmed before it can enter a valuation), and the endpoint says so
explicitly rather than guessing. See `app/domain/valuation_view.py` and
ROADMAP.md's Phase 3 section for exactly which of §18-26's nine models
this is and isn't wired to live data.

### Macro data (the hero spread)

```bash
python -m app.cli capture-market          # CSE market internals (P/E, turnover, foreign flow)
python -m app.cli cbsl --days 10          # CBSL T-bills, policy rate, CPI, FX
python -m app.cli backfill-index          # ~1 year of ASPI closes (index only)
python -m app.cli registry                # issuer registry, incl. delisted names (§7)
python -m app.cli sectors                 # GICS industry groups from the exchange (§12)
python -m app.cli second-source-check     # cross-check today's closes against TradingView (Part II §5.2)
python -m app.cli archetypes              # propose §16 archetypes from GICS — review every one (Appendix P2)
python -m app.cli spread                  # §29's equity-yield-minus-T-bill spread
```

`cbsl` honours CBSL's published `robots.txt` `Crawl-delay: 10`, so it is
deliberately slow — about 10 seconds per weekday fetched. Editions are
archived back to 2013 if you want history: `--start 2013-01-01` (expect
many hours; run it in chunks).

### Optional: populate the review queues

The Review screen is empty until ingestion has scraped something. Corporate
actions are rate-limited to >=2s per request (§5), so the full sweep of
283 lines takes 10+ minutes — start with a few:

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
