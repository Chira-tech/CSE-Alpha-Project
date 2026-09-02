# Data Integrity, Cross-Verification & Validation Framework — implementation status

Source: product-owner spec, 3 Sep 2026. Model simplified at the owner's
instruction: **binary, not a status ladder.** A fundamentals value
either passes every check and is available to the valuation engine, or it
fails one and goes to the existing human review queue. No
`VERIFIED / NEEDS_REVIEW / …` states, no numeric confidence score.

```
Extract → Verify → Cross-Check → Reconcile → Validate → (queue if failed) → Calculate
```

## What runs

| Piece | Where |
|---|---|
| The gate — per-line pass/fail for one filing | `app/domain/fundamental_validation.py` `validate_filing()` |
| Year-on-year trend check (§5) | same module, `check_series_trend()` |
| Independent-source majority vote (§3-4) | `app/domain/fundamental_majority_vote.py` `resolve()` |
| Sweep every filing, persist verdicts | `app/domain/fundamental_validation_view.py` `revalidate_all()` |
| Verdict store | `fundamental_validations` table (migration 0024) — `passed`, `failures_json`, `method`, `checked_at` |
| Valuation-engine gate | `app/domain/point_in_time.py` `fundamentals_as_of(exclude_validation_failed=True)` — a failed row is dropped before the engine sees it |
| Nightly job | `validate_fundamentals` — registry + runner + scheduler (01:20 Colombo, after auto-confirm, before the scoreboard recompute) |
| Company-wide grid (§17) | `app/domain/fundamental_validation_grid.py` → `GET /data-health/validation` → "Data-integrity validation" section on the Data Health screen |

## The checks (Phase 1-3)

1. **Accounting identities** (§6) — assets = equity + liabilities, revenue − cost of sales = gross profit, pre-tax − tax = net income, CFO + investing + financing = Δcash, current + non-current = total (both sides). Off by more than Rs 1,000 (publication rounding) → fail every line in that identity.
2. **Magnitude plausibility** (§8) — a line a millionth or less the size of the filing's largest value is a corrupted read (dropped digit, stray footnote number).
3. **Year-on-year trend** (§5) — a confirmed annual series 2020→present with a ≥10× step between consecutive years (both values material, ≥2% of the line's own peak), or a sign flip on a line that should never be negative (revenue, the balance-sheet totals — profit lines are exempt, a loss year is ordinary). Catches thousands/millions unit confusion, dropped digits, wrong column, wrong period, consolidated-vs-standalone mixups.
4. **Independent-source agreement** (§3-4) — a check-failed row is *rescued* to pass when two sources still agree on the stored value (the flag was on a sibling line); when two sources agree on a *different* value, that is recorded as a provisional correction and the row stays in the queue. Corroborators today: the stockanalysis.com cache, and the same figure re-typed in a later filing's comparative column.

Live dev sweep: 11,702 filings, 105,707 confirmable rows, **2,975 fail** (~2.8%) and are in the queue instead of feeding valuations. 51 rescued by independent-source agreement.

## Audit trail (§15)

No separate table. `fundamental_validations` records the date, method, every failing check, and (Phase 3) the conflicting-source values and the provisional corrected figure. An actual value change goes through the existing §6 restatement versioning, which never overwrites the prior value. "Why does the system say X for this line in 2024?" is answerable end to end from those two.

## Deferred / blocked

- **Explicit unit columns** (`raw_value` / `source_unit` / `normalized_value`) and a **group-vs-standalone `basis` column** (§8, §12) — need PDF-extractor work, not just a check. The magnitude + trend checks already catch the unit-error and mixed-basis failure modes they target; the explicit columns would make the audit trail richer, not the gate stronger.
- **A second independent external provider** (§4's true three-source rule) — none reliably covers CSE small-caps beyond stockanalysis.com. The later-filing comparative column stands in as the third source. `resolve()` takes any number of corroborators, so a real provider slots straight in when found.
