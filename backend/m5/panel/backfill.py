"""Task 3 (brief §3) — historical backfill of `m5.panel`, respecting
`first_available_date` at every row (never using a value dated after the
panel row's own `as_of`) and re-running the valuation engine
point-in-time at each historical date. Not yet implemented — see
`docs/CLAUDE_CODE_BRIEF_M5.md` §0.5 D1(d)/(f): backfill is DELIBERATELY
lower priority than Task 2 (forward panel accumulation) per the 21 Aug
2026 decision — every week the forward snapshot isn't running is
proprietary data lost permanently, which a later backfill can never
recover."""
