# R1 T4B.2 — Human-in-the-loop visual review

Walked live against the real running app (local dev server, real
database, real data — never a fixture dataset, per the brief's own
"environment notes") via the Chrome extension across this session's own
work on each surface. Automated capture/screenshots and assertion
results live separately in `R1_QA_CAPTURE.md` (see that file's own
header for why some assertions there are scoped down from the brief's
literal wording); this document is the qualitative pass automation
cannot do.

For each surface: the five questions, then a numbered defect list with
severity (blocks a decision / degrades a decision / cosmetic) and a
proposed fix. Per the brief's own instruction, every blocks/degrades
item below was fixed during this session's own work (see `R1_FIX_LOG.md`
for what changed and when) — this document records the review that
drove those fixes, not a backlog still waiting on them, except where
explicitly marked open below.

---

## Today

1. **Ten-second test.** The dominant object is the ASPI card with its
   trend chips, immediately followed by the earnings-yield spread —
   correct per the UI spec's own instruction that the spread, not the
   index, should train the reader's instinct. "2 · What needs my
   attention?" is the second thing the eye lands on, which is right for
   a screen whose own governing constraint is "usually conclude with
   nothing to do."
2. **Decision test.** Real: the attention section links straight to the
   confirm queue with the actual blocking tickers named
   (`fundamentals_pending_by_ticker`), and the board section links to
   Opportunities with three real ranked rows already visible. A user can
   decide "go clear the queue" or "go look at candidate X" from this
   screen alone.
3. **Density test.** The regime-gauge "not built yet" notice is
   necessary honesty, not clutter — removing it would make the screen
   look complete when it isn't. Nothing else stood out as removable.
4. **Language test.** Clean. "Real gap-to-buy-below ranking (§25-26) —
   not yet §40's full risk-adjusted-return metric" reads slightly
   spec-internal (a real user doesn't know what §40 is) but is
   deliberately paired with a plain-English clause immediately after it
   in every instance checked, so it never stands alone.
5. **Calm test.** No alarm styling anywhere; attention items render as
   a plain bulleted list, not badges or counters with colour. Pass.

**Defects found this session (fixed):** header wasn't "Today's summary"
(T4.1.1, fixed); ASPI card had no trend context (T4.1.2, fixed);
portfolio block on this screen used three windows instead of the
brief's own four (T4.1.6, fixed).

---

## Companies

1. **Ten-second test.** The sortable price-change columns (5/10/15/30-day)
   are the dominant new object and read immediately as "here's what's
   moved." Correct emphasis for a screener.
2. **Decision test.** Real: sorting by momentum surfaces something to
   investigate further, and every row opens the real company file.
3. **Density test.** The "Coverage tiers are absent... §38 composite
   score DOES exist now" explanatory paragraph is long for a screener
   header — a returning user doesn't need this every visit. Cosmetic;
   collapsing it behind a `<details>` (the pattern already used
   elsewhere on this screen, e.g. Opportunities) would tidy this without
   losing the disclosure.
4. **Language test.** The momentum-chasing caveat ("Recent strength
   does not by itself indicate value...") is exactly right — plain,
   only shown when relevant (sorting by a price column), never
   patronising when not.
5. **Calm test.** Pass — Delta glyphs carry direction via hue+glyph, no
   raw red/green.

**Defects found this session:** none blocking; one cosmetic (item 3
above), not fixed — logged here as backlog per the brief's own "cosmetic
items go to a backlog, not scope creep" instruction.

**Accessibility note (cosmetic, not fixed):** company rows are plain
`<tr onClick>` elements (keyboard-reachable via `tabIndex`/`onKeyDown`,
so not a blocking accessibility gap), unlike Opportunities/Portfolio's
own ticker cells, which wrap the ticker in a real `<button>`. Same
outcome for a mouse or keyboard user, but the inconsistency is real and
was found live while building `scripts/qa_capture.py` (a `role=button`
locator that works against every other screen's ticker cell doesn't
match this one). Worth normalising for consistency, not urgency.

---

## Company detail (walked on JKH.N0000, a diversified holding, and
confirmed the routing table/valuation-withheld path separately via
COMB.N0000-shaped bank archetypes earlier in this session)

1. **Ten-second test.** The composite score card, now moved next to the
   price ladder (T4.3.5), is genuinely the dominant object — score,
   VerdictPill and the stacked bar all read together in the first
   glance. Correct per the brief's own "make it the visual anchor"
   instruction.
2. **Decision test.** Real, and layered: price ladder + composite score
   for "is this interesting at all", ratio cards with sector percentile
   for "why", valuation routing for "which method, why not the others",
   fair value range for "at what price". A user can reach "watch this /
   skip this" from this page alone.
3. **Density test.** This is still the longest page in the app by a
   wide margin — 12+ sections. Nothing individually is removable (each
   answers a real question this session's own users asked for), but a
   sticky mini-nav or collapsed-by-default sections below the fold
   (financial statement lines, corporate actions) would help a user who
   only wants the top-of-page verdict. Not built this session —
   flagged as a real, cosmetic-to-degrades-boundary item, not fixed.
4. **Language test.** The Ke `PlainExplainer` (T4.3.2) is the clearest
   writing on the page — states the number, what it does, why it's
   where it is, never a verdict. "What this tells you" (T4.3.7)
   explicitly disclaims generating a bull/bear case rather than faking
   one — reads as honest, not evasive, in context.
5. **Calm test.** Pass. The margin-of-safety and fair-value-range
   numbers are presented flatly, no urgency language ("act now",
   countdown, etc.) anywhere on the page.

**Defects found this session (fixed):** ratio table was a plain numeric
table with no verdict/percentile/path (T4.3.1); Ke had no plain
explanation (T4.3.2); valuation routing was three disconnected lists
(T4.3.3); composite score was buried below the fold (T4.3.5); financial
statement lines had no pagination or confirm-priority sort (T4.3.6);
"what this tells you" didn't exist at all (T4.3.7, built new).

**Open (degrades, not fixed this session):** the page-length density
issue in item 3 above.

---

## Portfolio

1. **Ten-second test.** Cost / live value / unrealised P&L, in that
   order, dominate — correct per the spec's own "P&L is what happened,
   fair value is what to do about it" ordering (fair-value/zone/sell-
   above sit further right in the table, not competing for first
   attention).
2. **Decision test.** Real: "Sell above" (T4.5.3) plus the attention
   flag chips per position (T4.5.4) together answer "should I still
   hold this."
3. **Density test.** Clean — nothing extraneous.
4. **Language test.** Attention flag labels are terse chips
   (title-tooltip for the real reason) — reads slightly cryptic at a
   glance before hovering, but this matches the calm-density tradeoff
   the rest of the app makes deliberately (a full sentence per flag per
   row would be noisier for a multi-position table).
5. **Calm test.** Pass — attention flags use the same calm chip styling
   as everywhere else, no colour-coded alarm.

**Defects found this session (fixed):** "Buy Below" was shown for held
positions, the wrong signal (T4.5.3, now "Sell Above"); no trend context
on the summary (T4.5.1, fixed); no attention flags at all (T4.5.4,
fixed).

---

## Macro

1. **Ten-second test.** The hero spread dominates, per its own explicit
   design intent (§29) — confirmed correct, not accidental, by this
   session's reading of the UI spec.
2. **Decision test.** Real, new this session: clicking a sector opens
   the drill-down with a real treemap, ranked constituents and gap-to-
   fair-value — "which name in this sector is most/least stretched" is
   answerable from this screen now, which it wasn't before T4.6.4.
3. **Density test.** The sensitivity matrix's own explanatory notice
   ("Read this matrix carefully...") is long but necessary — most cells
   read "n.s." or "—" today (real, honest, not a bug), and a user
   without that context would read the mostly-empty matrix as broken.
4. **Language test.** Clean throughout; "n.s." (not significant) is
   used consistently with a hover title explaining it, not left bare.
5. **Calm test.** Pass — the new heat-map cell shading (T4.6.2) is a
   single muted sequential scale, confirmed live (a maximum-magnitude
   real cell renders at 60% opacity of the brand token, not a
   saturated colour).

**Defects found this session (fixed):** no heat-map shading (T4.6.2);
no sector drill-down at all (T4.6.4, the brief's own "highest-value new
feature", built new — real squarified treemap, ranked table, macro
sensitivities carried through, real bug found and fixed live in the
treemap's own row/column orientation).

---

## Data health

Not walked with the same five-question depth this session (Phase 3's
export work was verified functionally — both downloads produce real
files, `scripts/verify_backup_restore.py` ran clean — rather than as a
qualitative UX pass). Recorded here as a real gap in this document's own
coverage, not silently omitted.

---

## Full journey walk: Today -> Opportunities -> open a ticker -> Portfolio -> Macro

Walked live this session in pieces (not as one uninterrupted session
timed end-to-end). What held together: every screen this session
touched links forward to the next logical screen (Today's board links
to Opportunities, every ranked/held ticker opens the same company file,
the company file's own back link correctly names whichever screen the
user actually came from — verified for Companies/Portfolio/
Opportunities/Macro all four, see `App.tsx`'s own `backLabel` logic).

**Real dead end found and fixed this session:** Macro's own sector
click didn't exist before T4.6.4 — a user curious about a sector had no
next action beyond the matrix's own cells. Now resolved.

**Real friction, not fixed:** the company file (see "Density test"
above) is long enough that a user arriving from Opportunities with one
specific question ("is the fair value real for this one") has to scroll
past several sections to reach it. Not a dead end, but not the fastest
path either.

**Not walked this session:** Journal and Lab were out of scope for this
brief's own remediation list and were not re-walked as part of this
review.
