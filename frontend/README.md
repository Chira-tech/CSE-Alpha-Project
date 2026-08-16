# Frontend — confirm-queue tool

This is **not** the Phase 2+ product frontend the UI & Experience
Specification designs in full (Today, Opportunities, Company File, etc.)
— those need a real screener/valuation API behind them, which doesn't
exist yet. This is a small, focused internal tool for the one thing that
was blocking daily use of Phase 1's work: reviewing and confirming the
draft corporate actions and AI-assisted financial-statement extractions
that ingestion produces (Master Spec §5's "mandatory human confirm
queue"), which until now could only be done by querying the database
directly.

It still follows the UI spec's design tokens (`design-tokens.css`, §16)
and its calm-by-default spirit (§1) — no bright red/green, tabular
numbers, restrained buttons — but it is deliberately plain: two tables,
inline editing, a confirm/reject action per row. Build the real product
screens against `design-tokens.css` when Phase 2 starts; this tool can
stay as-is or be folded into a "Data health" screen later (per the UI
spec's screen 9).

## Running it

Needs the backend running first (see the root README) with
`CORS` already configured for `http://localhost:5173` in
`backend/app/main.py`.

```bash
cd frontend
npm install
cp .env.example .env    # defaults to http://localhost:8000, edit if needed
npm run dev
```

Open http://localhost:5173. Enter your name once (persisted in the
browser) — every confirm/reject requires it, matching the backend's own
requirement that every review action is attributable.

`npm run build` produces a static `dist/` bundle; `npm run lint` type-checks
without emitting (there's no separate linter configured yet — TypeScript's
strict mode is doing that job for now).
