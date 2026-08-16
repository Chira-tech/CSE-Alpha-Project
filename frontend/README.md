# Frontend

Four screens over the Phase 1 data layer:

- **Market** — live ASPI and S&P/CSE sector indices. A live passthrough to
  cse.lk, labelled as such: nothing here is stored or point-in-time, and
  no model reads it. When the macro engine lands (Phase 5) this becomes
  the regime read with the earnings-yield-minus-T-bill spread as its hero
  chart (§29), which is the number that actually matters on this screen.
- **Companies** — every listed name (§10: analyse everything), searchable,
  click through to a company file with price history, corporate actions
  and extracted statement lines.
- **Review queue** — the confirm workflow for scraped corporate actions
  and AI-assisted financial figures (§5's "mandatory human confirm
  queue"). Until this existed, reviewing a draft meant querying the
  database by hand.
- **Data health** — coverage, feed freshness, queue depths, quarantined
  tickers (UI spec screen 9, §8/§50).

## What is deliberately missing

No fair values, composite scores, buy-below prices or coverage tiers. The
engines that compute them are Phases 2–3 and don't exist. The company file
lists those gaps in plain language instead, because the UI specification's
anti-pattern list is explicit that "a fake number that reaches a user once
destroys trust permanently."

This is also not yet the full nine-screen product the UI spec designs
(Today, Opportunities, Valuation workbench, Portfolio, Journal, Lab...) —
those need engines behind them. What's here follows the same design
tokens (`design-tokens.css`, §16) and the same five laws (§1): calm by
default, direction carried by glyph as well as hue, tabular figures,
missing data shown as missing.

## Running it

Backend first (see the root README's Quick start — it needs to be
bootstrapped with real data, or the screens will correctly render as
empty). CORS is already configured for `http://localhost:5173`.

```bash
cd frontend
npm install
cp .env.example .env    # defaults to http://localhost:8000, edit if needed
npm run dev
```

Open http://localhost:5173. On the Review screen, enter your name once
(persisted in the browser) — every confirm/reject requires it, matching
the backend's own requirement that review actions are attributable.

`npm run build` produces a static `dist/` bundle; `npm run lint`
type-checks without emitting (no separate linter yet — TypeScript strict
mode is doing that job).
