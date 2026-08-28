# R1 Open Issues

**OI-1 is RESOLVED as of this session — see "RESOLUTION" at the end of its
own section below.** Kept in full, unedited, above the resolution: this
is the audit trail, and the wrong turns (the first, disproven root-cause
theory) are as much a part of it as the right answer.

Per the brief's own §0: "If a phase reveals that a later task is impossible or
wrong, stop and record it here rather than improvising a workaround." This is
that stop.

---

## OI-1 (CRITICAL, BLOCKING) — Note-reference-number extraction bug, live in confirmed data

**Found during:** Phase 1, T1.2 (reconciliation with source). The automated
20-ticker sample hit a **10.0% mismatch rate** — five times the brief's own
2%-stop-the-release threshold — on its very first run. Investigating those
two mismatches by hand surfaced a systemic bug, not two isolated typos.

### What's wrong

`app.domain.financial_statement_parsing.split_label_and_values` strips a
leading note-reference token (a small footnote number printed right before
the real figure, e.g. `"Revenue  9  22,889,584  49,173,843"` where `9` is a
footnote marker, not data) **only when the line has strictly more numeric
tokens than the statement page's own detected column count**
(`len(numeric_tokens) > expected_value_columns`, `financial_statement_
parsing.py:1048`). This is the right idea for the case it was built for
(J.F. Packaging's real "Revenue 5 4,504,801 4,385,214 2,356,951 2,371,137"
— 5 tokens against 4 expected columns, correctly drops the `5`) — but when
the note-number-plus-real-columns count happens to EQUAL the page's
detected column count instead of exceeding it, the rule never fires, and
the footnote number is stored as `primary_value` — the number that becomes
`Fundamental.value`.

Confirmed directly against two real filings, downloaded fresh during this
audit (not assumed from the stored row):

| Ticker | Line | Period | Stored | Real value (re-extracted from source PDF, right now) | Ratio |
|---|---|---|---|---|---|
| RENU.N0000 | revenue | 2025-03-31 | **8** | 261,589,819 | ~32,700,000× understated |
| AINS.N0000 | net_income | 2026-06-30 | **9** | 22,889,584 | ~2,540,000× understated |

RENU's own row already carries a source snippet reading `"EXTRACTION
FAILED ARITHMETIC CHECK"` — the existing accounting-identity cross-check
(§ built earlier this project) correctly caught THAT one, and the row is
still `AI_ASSISTED`/unconfirmed, so it cannot yet enter a valuation (§8
working as designed).

**AINS did not have that protection and is already live.** Its row is
`provenance_tier=REPORTED`, `confirmed_by='human:claude-code (bulk confirm
19 Aug 2026, user-authorized after sample check; excl. flagged rows)'` —
i.e. an earlier session's bulk-confirm pass promoted this exact wrong
value into the tier that feeds real valuations, and it was not among
whatever it excluded as "flagged." `net_income` has no reciprocal
accounting identity to cross-check it against the way `revenue -
cost_of_sales = gross_profit` does, so nothing caught it.

### Blast radius (measured, not estimated)

A sweep of every `revenue` / `net_income` / `total_assets` / `total_equity`
/ `total_liabilities` / `profit_before_tax` / `total_comprehensive_income`
/ `operating_profit` row under 100,000 (a threshold no real listed
company's absolute LKR figure for any of these should fall under) found:

- **899 rows** total match this shape.
- **396 of them are `REPORTED` + human-confirmed** — i.e. currently
  eligible to feed a live valuation, across **88 distinct tickers**
  (≈30% of the 290-security universe).
- **503 are `AI_ASSISTED` and unconfirmed** — correctly held back from
  valuation by §8 today, but still wrong data sitting in the confirm
  queue waiting for a human (or a future bulk-confirm) to promote them.

**This 899 figure is not all bug.** A manual spot-check of 8 random rows
from the confirmed set found the bug pattern in 6 of 8 (RENU-shape:
COCR.N0000, LGL.X0000, HOPL.N0000, AINS.N0000, plus CBNK.N0000 which shows
a related-but-distinct split-digit symptom); 2 of 8 were false positives
of the crude `< 100000` filter — genuinely small figures that happen to be
correctly extracted (JKL.N0000, KFP.N0000). **The true confirmed-affected
count is very likely in the 200–300 range, not exactly 396** — this audit
does not yet know the precise number, because knowing it precisely means
re-verifying against the source PDF the same way T1.2 did, at scale. That
re-verification is proposed as OI-1's own resolution step below, not done
yet — deliberately not run without sign-off given its real cost (see
"Recommended path" below).

### A second, independent finding surfaced while investigating this

`app.jobs.reconciliation.is_quarantined` and its `DataAlert` mechanism
are documented, in their own docstrings, as excluding a quarantined ticker
"from every model until a human resolves it" (§7/§50). **They do not.**
`grep` across `app/domain/opportunity_ranking_view.py` and `app/domain/
portfolio_valuation_view.py` finds zero references to `is_quarantined` or
`DataAlert` in either. Quarantine is currently checked and displayed in
exactly one place — the company-file badge in `app/api/routes/
securities.py` — and nowhere else. A quarantined ticker's numbers still
flow into Opportunities ranking and Portfolio valuation today. This means
raising a `DataAlert` for the 88 affected tickers would NOT actually stop
their bad figures from being used anywhere except that one badge — it
was the obvious first idea for a quick mitigation, and it would not work.

### CORRECTION (after deeper investigation) — this is likely stale data, not a live code bug

The paragraph above, written right after finding RENU/AINS, assumed the
note-reference-drop rule's `len(numeric_tokens) > expected_value_columns`
gate was the live, currently-reproducible cause. Direct verification says
otherwise:

Calling `extract_financial_statement_candidates` (today's real,
unmodified pipeline) against AINS.N0000's real filing PDF right now
finds **two** occurrences of `net_income` in the same document — page 1
("Profit for the Period 9 22,889,584 49,173,843") extracts CORRECTLY
today as `(22889584, 49173843)`, the leading "9" properly dropped. `build_
fundamental_drafts`' own documented "first occurrence wins" rule means
page 1's correct reading is what a fresh ingestion run would store — not
the wrong "9" actually sitting in the database. **The stored "9" is
stale**: extracted at some earlier point (before whatever made page 1's
extraction work correctly today, or from a different code path
entirely), then promoted to `REPORTED` by the 19 Aug bulk-confirm pass
without anyone re-running extraction or genuinely checking the value
against ~22.9M staring back from the very next column over.

Page 3 of that same AINS filing has an independent, genuinely-still-live
extraction limitation ("Profit for the Period 17,317,450 3 7,339,693" →
`(17317450, 3, 7339693)`, should be `(17317450, 37339693)`) — but it's
already a KNOWN, DOCUMENTED, deliberately-unfixed limitation of
`_repair_split_leading_digits` (see that function's own "SECOND,
CONFIRMED REAL LIMITATION" docstring paragraph, citing PAP.N0000's real,
analogous case from 18 Aug) — not something newly found here, and it
doesn't affect AINS's stored value anyway, because page 1 (correct) wins
over page 3 (wrong) under the first-occurrence rule.

**Revised conclusion: there is currently no confirmed, live, reproducible
parsing-code bug behind OI-1.** The real defect is (a) stale extractions
sitting in the database from before some earlier fix, and (b) a bulk-
confirm process on 19 Aug 2026 that promoted them to `REPORTED` without
actually re-verifying each value despite its own commit note claiming a
"sample check." A code fix may still turn out to be warranted — the full
re-verification sweep (step 2 below), running now, will show definitively
whether ANY of the 396 rows are still wrong under TODAY's code (real bug,
worth a tested fix) versus merely stale (data-only remediation, no code
change needed). Written up honestly here rather than shipping a
speculative parsing change against an unconfirmed diagnosis — exactly the
"confident, precise, entirely fictional" failure mode this whole project
exists to avoid, just nearly committed by the audit process itself this
time.

### Recommended remediation path (not yet executed — needs a decision)

1. **Immediate, safe, fully reversible**: revert the confirmed-bad rows to
   `provenance_tier=AI_ASSISTED, confirmed_by=NULL` — i.e. undo the
   erroneous confirmation, not delete anything. This puts them back
   behind the already-working §8 gate (`can_enter_valuation`), which — 
   unlike quarantine — genuinely is checked everywhere a valuation reads
   fundamentals. Precise targeting needs the re-verification sweep in
   step 2 first, so this doesn't also revert genuinely-correct small
   figures.
2. **Full re-verification sweep**: rerun T1.2's exact method (download
   the real filing, re-run the real extraction pipeline, compare) across
   all 253 distinct `source_url`s behind the 396 confirmed candidates —
   not a sample this time, the whole set. At ≥2s pacing plus real
   download/parse time per filing, this is roughly 30–45 minutes of
   background wall-clock time hitting cdn.cse.lk. Produces an exact,
   verified list of which rows are actually wrong (expected ~200-300 of
   the 396) rather than the crude threshold used to find them.
3. **The parsing fix itself**: strip a leading note-reference token
   whenever the first one or two tokens are shaped like a note reference
   AND immediately followed by a properly comma-grouped value — a
   shape-based signal, not a column-count-based one — so the rule fires
   regardless of whether the page's detected column count happens to
   match. Needs real regression tests against BOTH known-good shapes
   already in the test suite (J.F. Packaging's real "note ref, more
   columns than expected" case must keep working) and the new failure
   shapes found here (RENU, AINS, COCR, LGL, HOPL) before it ships —
   exactly the "write the test first" discipline this project already
   uses everywhere else in `financial_statement_parsing.py`. Not
   attempted in this pass; a change to core parsing logic without that
   test coverage risks trading one silent corruption class for another.
4. **Re-run the sweep once more after the fix** to confirm the count of
   newly-correctly-extracted values, and re-confirm (properly, this time)
   whichever ones are now genuinely right.
5. **Separately: fix or remove the false promise in `is_quarantined`'s
   docstring** — either wire `opportunity_ranking_view` and `portfolio_
   valuation_view` to actually check it (matching what §7/§50 and the
   docstring already claim), or correct the docstring to state the real,
   narrower scope. Leaving the claim as-is is itself a defect independent
   of OI-1's own bug — a future reader (human or agent) trusting that
   docstring would wrongly believe quarantine is a working safety net for
   exactly this kind of problem.

**None of steps 1–5 above have been executed.** Step 1 in particular
touches 88 real companies' live data and was deliberately not done
without asking first, given its scale and the fact that step 2's precise
targeting hasn't run yet.

---

### RESOLUTION — 23 Aug 2026

The full re-verification sweep (`scripts/reverify_suspicious_fundamentals.py`,
no `--skip-network`, all 253 distinct filings, not a sample) ran to
completion: **`docs/audits/R1_OI1_REVERIFICATION.md`**.

- **301 of 396 candidates were `confirmed_correct`** — the stored figure
  IS what today's pipeline produces. False positives of the crude
  `< 100000` magnitude filter that found the candidate set (real, small,
  correctly-extracted figures — e.g. KFP.N0000's real 9,758 net income
  for a small quarter).
- **95 were `confirmed_still_wrong`** — today's pipeline, run fresh
  against the real live source PDF, produces a DIFFERENT (and always
  much larger) value than what's stored. Spot-checking several of these
  95 individually (PLR.N0000, CALF.N0000, AAF.N0000, more) the same way
  RENU/AINS were checked earlier in this document: **today's pipeline
  gets every one of them right on the FIRST matching page** — e.g.
  PLR.N0000's real page 190 already reads `"Revenue 4 11,031,333,018
  8,259,800,877"` as `(11031333018, 8259800877)` correctly today, with
  the leading "4" note reference properly dropped. This generalises the
  AINS/RENU finding from the CORRECTION above to all 95: **there is no
  live, currently-reproducible parsing bug behind OI-1 at all.** Every
  one of the 95 wrong values is stale — extracted at some point before a
  parsing improvement now in the codebase, then promoted straight to
  `REPORTED` by the 19 Aug 2026 bulk-confirm pass without anyone
  re-running extraction or actually checking the number.
- **0 were unverifiable.**

**Remediation applied** (`scripts/remediate_oi1.py --apply`, both a
dry-run and the real run kept in this session's own record): all 95
confirmed-wrong entries (101 physical rows — several matched more than
one stored row) were reverted to `provenance_tier=AI_ASSISTED`,
`confirmed_by=NULL`, `confirmed_at=NULL`, and **`value` corrected to the
figure the live re-verification actually confirmed** — never silently
re-promoted to `REPORTED`. `source_snippet` on each row now carries a
dated remediation note (the original wrong value, the corrected value,
and why) ahead of the original extracted snippet, so the audit trail
survives in the row itself, not only in this document. A human still has
to look at each one via the confirm queue (§8) — including, now, via the
corroboration-gated bulk-confirm path (R1 T2.5) built directly in
response to this incident, which would have refused every one of these
95 rows in the first place had it existed on 19 Aug (none of them had a
genuinely independent REPORTED corroborator; they were promoted on a
"sample check" that evidently wasn't one).

Verified after remediation: zero rows remain `REPORTED` + confirmed +
matching any of the 95 originally-wrong keys; full backend test suite
still 1271/1271 (data-only change, no schema or code-path touched by the
remediation itself).

**Item 5 of the original remediation path — the `is_quarantined` gap —
is still open**, tracked separately as OI-3 below, since it's a real,
independent defect (not part of OI-1's own root cause) rather than
something the sweep or remediation touches.

---

## OI-3 — `is_quarantined` doesn't actually gate anything except one UI badge

Found while investigating OI-1, confirmed separately: `app.jobs.
reconciliation.is_quarantined` and the `DataAlert` table it reads are
documented, in their own docstrings, as excluding a quarantined ticker
"from every model until a human resolves it" (§7/§50). They do not.
`grep` across `app/domain/opportunity_ranking_view.py` and `app/domain/
portfolio_valuation_view.py` finds zero references to `is_quarantined` or
`DataAlert` in either — quarantine is checked and displayed in exactly
one place (`app/api/routes/securities.py`'s company-file badge) and
nowhere else. A quarantined ticker's numbers still flow into Opportunities
ranking and Portfolio valuation today.

**Status: RESOLVED, same session.** Option (a) was the real fix, and
it's done: `opportunity_ranking_view.opportunity_ranking_for` now checks
`is_quarantined` per ticker and routes a quarantined name to `excluded`
with the quarantine reason as its only warning, never ranked, before any
valuation work runs for it. `portfolio_valuation_view.value_position`
checks the same thing and withholds every DERIVED field (fair value,
price-ladder zone, buy-below, sell-above, margin of safety, dispersion)
for a quarantined holding while still showing the real, directly-observed
price/quantity/market-value — hiding a real position's price would be
worse than a caveated valuation gap. Two new regression tests
(`test_a_quarantined_ticker_is_excluded_with_the_quarantine_reason_not_ranked`,
`test_a_quarantined_holding_shows_price_but_withholds_fair_value`), full
suite 1273/1273. The Data Health screen's own quarantine-list copy was
also corrected to stop claiming the broader guarantee before this fix
landed, and now describes what's actually true.

---

## OI-4 — OI-1's reverification scope was too narrow: found live during Phase 5

While building an independent valuation for LOFC.N0000 (one of Phase 5's
5 randomly-selected tickers — see `R1_VALIDATION.md`), its confirmed
`interest_expense` for 2025-03-31 (annual) read `4.2`, and its confirmed
`income_tax_expense` for the same period read `13` — both obviously
implausible next to the surrounding billions-scale figures. Checked
against the real source PDF (`https://cdn.cse.lk/cmt/upload_report_file/
1073_1756460835256.pdf`, page 105): the real text is `"Interest expense
4.2 (26,211,477,746) (37,019,229,768)"` and `"Income tax expense 13 -
-"` — in both cases the stored value is the NOTE-REFERENCE number
(`"4.2"` = note 4.2, `"13"` = note 13), not the real figure. Exactly
OI-1's bug pattern.

**Root cause, confirmed by re-running the CURRENT extractor against the
same real page text:** the present-day code gets both lines right —
`interest_expense` correctly resolves to `-26,211,477,746`, and
`income_tax_expense` correctly produces no candidate at all (the real
line shows a nil marker for both periods, and `split_label_and_values`
deliberately returns `None` when every value is nil rather than
inventing a zero). So this is stale data from before a prior fix,
exactly like OI-1 — **not** a currently-live extraction bug — but OI-1's
own reverification script (`scripts/reverify_suspicious_fundamentals.py`)
only ever checked 8 specific statement lines (`revenue`, `net_income`,
`total_assets`, `total_equity`, `total_liabilities`, `profit_before_tax`,
`total_comprehensive_income`, `operating_profit`) — `interest_expense`
and `income_tax_expense` were never in that set, so this exact
contamination class slipped through the earlier sweep undetected on
every OTHER statement line it didn't check, for every ticker, not just
LOFC.

**Fixed, scoped:** both LOFC.N0000 rows corrected (`interest_expense`
-> -26,211,477,746, `income_tax_expense` -> 0), reverted to AI_ASSISTED
pending re-confirmation, source_snippet notes the correction and why.

**NOT fixed, named rather than silently dropped:** a full re-run of
OI-1's reverification sweep across every OTHER confirmed statement line
(not just the original 8) is real, separate, universe-wide work this
session did not do — the two LOFC corrections above are a targeted spot
fix from Phase 5's own random sample, not a systematic sweep. A
`note-reference contamination on line X` bug of this shape could exist
on any confirmed row for any line outside the original 8, for any
ticker, and remains genuinely unknown at the scale of "how many."

---

## OI-2 — Brief's own tech-stack description doesn't match this repo

Confirmed at the start of this work and already resolved by direction
from the user: the brief describes "Next.js frontend" and a `cse_engine`
Python package; this repo is Vite + React and `app/`. Proceeding against
the real stack per explicit instruction. Recorded here only so this
audit's own trail is complete, not as an open question.
