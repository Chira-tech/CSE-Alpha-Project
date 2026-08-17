# Frontend

Built against the **UI & Experience Specification v1.0**. Where the spec is
specific, this follows it literally — see "Spec compliance" below.

## Screens

The navigation is §7.1's, exactly: six primary destinations, a rule, then
two advanced ones.

| Destination | State |
|---|---|
| **Today** | Built. §8's four questions; sections 1–2 answered from real data, 3–4 marked as awaiting their engines. |
| **Opportunities** | Awaiting Phases 2–3 (needs the fundamental, valuation and price engines). |
| **Companies** | Built. All listed names, searchable, each with a company file — now including a "Fair value (§18-26)" section: justified P/B, residual income, triangulation, margin of safety and the price ladder, wired to real stored data (`GET /valuation/{ticker}`). Most companies still honestly show no fair value yet — almost none have a human-confirmed fundamentals period (§8) — and DCF/DDM/SOTP/asset-based stay unwired regardless of confirmation (ROADMAP.md's Phase 3 section says why). |
| **Portfolio** | Awaiting Phase 8. |
| **Macro** | Partly built — the live sector index board exists; the regime engine (§29–34) does not. |
| **Journal** | Awaiting Phase 4. |
| **Lab** | Awaiting Phase 8. |
| **Data health** | Built. §9's screen: coverage, freshness, queue depths, quarantine. |
| **Confirm queue** | Built. Reached from Data health — §7.1 specifies eight destinations and adding a ninth would misrepresent the IA. |

Destinations whose engines don't exist are listed rather than hidden, and
each says plainly what will live there and which phase builds it. Hiding
them would misrepresent the product's shape; filling them with sample
content is the §17 placeholder anti-pattern, which the spec forbids
outright ("a fake number that reaches a user once destroys trust
permanently").

## What is deliberately absent

Composite scores and coverage tiers — their engine is Phase 2. The API
omits those fields entirely rather than returning null, because a null
is too easy to render as "0". Fair value and a buy-below price are no
longer categorically absent (see the Companies row above); the company
file's price-ladder bar uses the five `--zone-*` tokens in
`design-tokens.css`, which were defined against §26 before this was the
first thing to actually read them.

## Spec compliance

Fifteen automated checks run against the source (see the audit block in
the session notes / re-runnable with grep): no raw hex outside the token
file, no pill buttons, no weight above 600, spacing from the 4px scale
only, `prefers-reduced-motion` and `prefers-color-scheme` both honoured,
2px brand focus rings, skip link, evidence panel as a slide-over rather
than a modal, tabular figures, direction carried by glyph as well as hue,
nulls as "Data unavailable", no BUY/SELL verdict anywhere, explicit paging
rather than infinite scroll.

Specific implementations worth knowing about:

- **§3 type scale** — `.t-display` / `h1` / `h2` / `h3` / `.t-body` /
  `.t-data` / `.t-label` / `.t-caption` are the only text sizes. Three
  weights (400/500/600). Prose capped at 68 characters.
- **§4 shell** — 240px persistent rail, 1360px max content, collapsing to
  a horizontal bar under 1024px.
- **§5 numbers** — `format.ts` returns the "Data unavailable" sentinel
  from every formatter, so a caller physically cannot render a gap as a
  value. Magnitudes abbreviate (`4.9m`, `1.2bn`); percentages carry one
  decimal and an explicit sign.
- **§14 evidence panel** — click the closing price on a company file. It
  slides in from the right at 480px with a *transparent* click-catcher,
  not a dimming scrim, because the spec's whole objection to modals is
  that they block the context you're comparing against.
- **§15.1 six states** — `components/states.tsx`. `ErrorState`'s props are
  named `whatFailed` / `whatItAffects` / `whatStillWorks` /
  `whatHappensNext` so an incomplete error message doesn't type-check.
- **§2.2 ochre discipline** — `--caution` is used only for data-quality
  and system state (stale feed, quarantine, pending review), never for
  market movement, so "the data is wrong" never reads as "the company is
  in trouble".

### One deviation from the published tokens, deliberately

§16's token block defines dark mode only under an explicit
`[data-theme="dark"]` attribute, but §15.2 requires respecting
`prefers-color-scheme`. As published those two conflict: a user whose OS
is dark and who never touches an in-app toggle would get the light
palette. `design-tokens.css` now also applies §2.4's dark values under a
`prefers-color-scheme: dark` media query, guarded so an explicit
`[data-theme="light"]` still wins. No new colours were invented.

## Running it

Backend first (see the root README — it must be bootstrapped, or the
screens will correctly render as empty). CORS is preconfigured for
`http://localhost:5173`.

```bash
cd frontend
npm install
cp .env.example .env    # defaults to http://localhost:8000
npm run dev
```

Open http://localhost:5173. `npm run build` produces a static bundle;
`npm run lint` type-checks (TypeScript strict mode is the linter for now).
