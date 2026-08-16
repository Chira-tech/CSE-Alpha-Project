# Frontend — not started

Per the build sequence (Master Spec §54 / ROADMAP.md), the frontend begins
in Phase 2 ("ranked screener UI, stock file v1") once there's a real API to
point it at. Building screens against endpoints that don't exist yet would
just be static mockups pretending to be product.

`design-tokens.css` is transcribed verbatim from the UI & Experience
Specification §16 so it's ready to drop into the Vite/React project when
that phase starts — colours, type scale, spacing, elevation and motion
tokens, plus dark mode overrides. Stack per the spec: React + Tailwind +
Recharts (§51, UI spec header).

Read the UI spec's §1 (five design laws) and §17 (anti-patterns) before
writing the first component — the whole point of that document is that a
dense financial interface drifts toward manufactured urgency and gamified
engagement unless someone writes down, in advance, exactly what it must
never do.
