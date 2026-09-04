"""
Deterministic line-item extraction from CSE financial-statement PDF text.

Master Spec §5 describes the intended pipeline as "PDF table extraction ->
LLM-assisted line-item mapping -> mandatory human confirm queue." This
module is NOT that — it's a Phase-1 stand-in that gets a genuinely useful
subset of line items (see CANONICAL_LABELS below) without an LLM call,
using patterns verified against a real annual report (J.F. Packaging PLC,
FY2025/26, downloaded via the verified `getFinancialAnnouncement`
endpoint — see app/ingestion/README_ENDPOINTS.md). Wiring an actual LLM
extraction step is a real Phase-1/2 decision that needs an API key and a
cost/model choice from the user — not something to bake in silently — so
it's tracked as an open item rather than implemented here. Every value
this module produces is written with provenance_tier=AI_ASSISTED and
cannot enter a valuation until a human confirms it (§8) — see
app/api/routes/fundamentals.py.

WHY extract_tables() ISN'T USED: pdfplumber's table detector relies on
ruled lines/borders. CSE annual report statement pages are typically
positioned text with no visible grid, and `extract_tables()` on a real
example collapsed the entire page into one text blob plus a column of
numbers completely disconnected from their labels — useless. Working from
`extract_text()`'s line-by-line output instead, with a right-to-left
token scan to separate a label from its trailing numbers, is what
actually works on real documents.

THE NOTE-REFERENCE PROBLEM: a statement line often has a note number
between the label and the actual values, e.g.
    "Revenue 5 4,504,801 4,385,214 2,356,951 2,371,137"
but not always:
    "Total Assets 3,807,110 3,722,727 3,559,834 3,453,018"
A note reference is a short, comma-free, dot-separated number ("5", "6.1",
"24.1.1", "10.1") immediately followed by a properly comma-formatted
value. Confusing one with a value would silently extract "5" as Revenue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# Strict: a well-formed figure is either comma-grouped in threes
# (4,453,103) or has no grouping at all (453103), optionally negative via
# parentheses and optionally with decimals. Deliberately does NOT match a
# fragment like ",453,103".
#
# The earlier version of this pattern was `^\(?[\d,]+(\.\d+)?\)?$`, which
# happily accepted a leading comma — and that permissiveness silently
# corrupted a real filing. See _repair_split_thousands below.
_VALUE_RE = re.compile(r"^\(?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?$")
# Verified on J.F. Packaging PLC's cash flow statement (FY2025/26): a line
# item split across two notes is referenced as "11/13" (PPE note 11 +
# intangibles note 13), not the dot-separated sub-note form ("6.1", "20.1.2")
# this pattern already handled. A slash never appears in a real value
# (Rs.000 figures are digits/commas/parens only), so allowing it here is
# safe and motivated by a real filing, not a guess at wording variance.
_NOTE_REF_RE = re.compile(r"^\d{1,3}([./]\d{1,3}){0,3}$")
_NIL = "-"

# A "Change %"/"Variance %" column between real value columns — verified
# live on two independent real filings: Hikkaduwa Beach Resort PLC's
# ("Revenue from contracts with customers 163,267,528 360,646,918 (55%)
# 1,878,722,846") and Amãna Bank PLC's ("Profit for the Period 1,124,622
# 901,334 25% 622,661 467,208 33%") real interim statements for the
# quarter ended 30 June 2026. Genuinely common — both filings are
# otherwise ordinary IFRS-style statements, not edge cases. Before this
# pattern existed, `split_label_and_values`'s right-to-left scan hit the
# first "%"-shaped token and stopped immediately, folding every REAL
# value to its left into `raw_label` — so `match_canonical_label` was
# handed a corrupted label like "revenue from contracts with customers
# 163,267,528 360,646,918 (55%)" instead of "revenue from contracts with
# customers", and the line silently produced no draft at all. Matched and
# DROPPED (never kept as a `values` entry, never counted toward
# `expected_value_columns`) — it is a computed comparison, not one of the
# statement's own reported figures.
_VARIANCE_PCT_RE = re.compile(r"^\(?-?\d+(?:\.\d+)?%\)?$")

# pdfplumber sometimes emits a space between a number's leading digit and
# its first comma group: "4 ,453,103" instead of "4,453,103". Observed on
# J.F. Packaging PLC's June 2026 interim statements (but NOT on its annual
# report — same company, same layout family, different rendering).
#
# Left unrepaired this is worse than a parse failure: the line still
# tokenises, the leading "4" looks exactly like a note reference, gets
# dropped by the note-reference rule, and "Total Assets" is recorded as
# 453,103 instead of 4,453,103 — off by four billion rupees and entirely
# plausible on screen. Repairing before tokenising, and refusing
# comma-leading fragments after, closes it from both directions.
_SPLIT_THOUSANDS_RE = re.compile(r"(\d)\s+(?=,\d{3})")

# A THIRD real pdfplumber space artifact, distinct from both patterns
# above: a stray space landing right after a negative value's own
# OPENING parenthesis — "( 84,645)" instead of "(84,645)". REAL BUG THIS
# CLOSES, found live (28 Aug 2026) tracing Chemanex PLC's real confirmed
# `cost_of_sales`: left unrepaired, `line.split()` tokenises "( 84,645)"
# as TWO separate tokens, a bare "(" and "84,645)" — and a lone "("
# matches none of `split_label_and_values`' own four numeric-token
# shapes (`_VALUE_RE`, `_NOTE_REF_RE`, `_VARIANCE_PCT_RE`, the nil
# marker), so the right-to-left numeric-token scan stops dead at that
# bare "(" and swallows the REST of the real value into the label
# instead. `(?=\d)` in the lookahead is what keeps this narrow: a
# genuine label-text parenthetical ("(Loss)", "(Increase)/Decrease in
# Inventories") is never touched, because a letter, not a digit, follows
# the opening paren there.
_SPLIT_OPEN_PAREN_RE = re.compile(r"\(\s+(?=\d)")


def _repair_split_thousands(line: str) -> str:
    line = _SPLIT_OPEN_PAREN_RE.sub("(", line)
    return _SPLIT_THOUSANDS_RE.sub(r"\1", line)


def _is_lone_leading_digit(token: str) -> bool:
    return len(token) == 1 and token.isdigit()


def _repair_split_leading_digits(numeric_tokens: list[str]) -> list[str]:
    """A DIFFERENT real pdfplumber artifact from `_repair_split_thousands`
    above (that one repairs a stray space landing right before a number's
    own first comma; this one repairs a stray space landing one character
    earlier, splitting off the number's own leading digit as a
    seemingly-standalone token). Found live (18 Aug 2026) on Wealthtrust
    Securities PLC's (WLTH.N0000) real interim statement for the period
    ended 30 June 2026: "Total Assets 4 7,325,768,494 4 3,942,985,474"
    tokenises as four numeric-looking tokens ("4", "7,325,768,494", "4",
    "3,942,985,474") when only two real values are printed —
    47,325,768,494 and 43,942,985,474. Confirmed by cross-checking every
    real asset line on the same page against the balance sheet's own
    printed total: reading every line this way and summing reconciles to
    the real total_assets figure to within LKR 2 (manual transcription
    slop, not evidence against the reading) — not a coincidence.

    DELIBERATELY NARROW to avoid corrupting the real, already-working
    case this could otherwise break: J.F. Packaging PLC's own real
    "Revenue 5 4,504,801 4,385,214 2,356,951 2,371,137" line, where "5"
    IS a genuine note reference, not a split digit. That line has an ODD
    number of numeric tokens (5) and is untouched here — it's left to
    the existing excess-note-reference drop logic below, which already
    handles it correctly. This repair only fires when the ENTIRE numeric
    tail alternates lone-single-digit, full-value, lone-single-digit,
    full-value — i.e. every one of the line's real values was
    independently split the same way, not just one isolated leading
    token — a pattern a single genuine note reference could not produce
    by coincidence across multiple columns. KNOWN, UNADDRESSED RISK: a
    real filing with a genuine single-digit note reference immediately
    before its ONLY value column (an exact 2-token "note value" line)
    would be indistinguishable from this pattern and would be wrongly
    merged — no real filing exhibiting that exact shape has been seen
    yet; if one turns up, this heuristic needs a stronger signal than
    token shape alone (e.g. cross-checking against `check_accounting_
    identities`, which is what actually caught this bug in the first
    place).

    A SECOND, CONFIRMED REAL LIMITATION (found 18 Aug 2026, Panasian
    Power PLC / PAP.N0000's real interim statement for the quarter ended
    30 June 2026, NOT fixed here): this repair requires EVERY column on
    the line to be split the same way, uniformly — but PAP's own real
    "Inventories" row splits only 2 of its 4 real value columns this way
    ("Inventories 3 17,353,093 1 39,446,076 1 ,472,811 1 ,267,145" — the
    last two columns were already fully repaired by `_repair_split_
    thousands` above, since THEIR stray space happens to land right
    before a comma, while the first two columns' stray space lands one
    character earlier). Cross-checked against the real page's own current-
    assets subtotal (the four real components sum to it exactly): the
    true first column is 317,353,093, not the 17,353,093 this function
    currently returns (its non-uniform pairs make it bail out entirely,
    and the leading "3" is then wrongly dropped by the excess-note-
    reference logic below, which cannot tell it apart from a genuine
    note reference). A right-to-left greedy per-column reconstruction
    would fix this row, but was deliberately NOT implemented: tracing it
    through by hand shows it reintroduces the EXACT J.F. Packaging false-
    positive above (a genuine trailing note-reference "5" immediately
    before a real, complete, unsplit final value becomes syntactically
    indistinguishable from "5" being that value's own split leading
    digit) the moment the row's split/unsplit columns are mixed rather
    than uniform — i.e. the two known real filings this module has
    evidence for actively conflict with each other. This affects `inven-
    tories` on this one specific real row and nothing checked by
    `check_accounting_identities` (every total/subtotal line on PAP's
    real balance sheet is either fully split or fully unsplit, never
    mixed) — see test_extract_candidate_lines_finds_every_canonical_
    item_on_paps_real_balance_sheet's own comment. Left as a named, real,
    disclosed gap rather than a forced fix that risks corrupting the
    WLTH/JFP cases already verified above.

    A FOURTH, CONFIRMED REAL CASE (found 19 Aug 2026, Asia Asset Finance
    PLC / AAF.N0000's real FY2022 annual report, ODD token count this
    time, NOT fixed here either): "Profit for the year 1 18,561,733
    45,196,117" tokenises as `["1", "18,561,733", "45,196,117"]` — 3
    tokens, so this function's own `len(...) % 2 != 0` guard returns it
    untouched, same as it correctly does for J.F. Packaging's genuine
    "Revenue 5 4,504,801 ..." note-reference line. The lone "1" then
    passes `_VALUE_RE` on its own (a bare single digit is syntactically
    a valid, if implausible, value) and gets read as net_income = 1
    instead of the real 118,561,733 — confirmed by cross-referencing
    the SAME period's OTHER, correctly-parsed extraction attempt
    (version 2 of this filing, which failed `check_accounting_
    identities` for an unrelated reason and shows net_income =
    118,561,733 there). A rule that merges a lone leading digit whenever
    doing so produces a syntactically valid number would ALSO wrongly
    merge J.F. Packaging's genuine "5" into "4,504,801" — traced by
    hand, that exact JF Packaging line and this AAF line are
    syntactically indistinguishable from token shape alone (both:
    single leading digit, followed by a comma-grouped value that's
    valid whether or not the digit is prepended). The real
    discriminator is MAGNITUDE plausibility relative to the rest of the
    same filing (a `net_income` of 1 next to a `total_assets` of ~19.3bn
    is absurd; JF Packaging's "5 4,504,801" as a note reference is not),
    which is exactly the kind of cross-line, whole-statement signal this
    function's own docstring already names as the missing piece for the
    WLTH/JFP case above — not solvable here, at the single-line/single-
    statement level, without the same risk of reintroducing that
    verified regression. `app.ingestion.financial_reports_archive_
    loader`'s confirm-queue review is the current, real backstop for
    this specific shape of error until a genuine cross-statement
    plausibility check exists to catch it automatically."""
    if len(numeric_tokens) < 2 or len(numeric_tokens) % 2 != 0:
        return numeric_tokens
    merged: list[str] = []
    for i in range(0, len(numeric_tokens), 2):
        lead, rest = numeric_tokens[i], numeric_tokens[i + 1]
        if not _is_lone_leading_digit(lead):
            return numeric_tokens  # not a uniform split pattern; leave untouched
        candidate = lead + rest
        if not _VALUE_RE.match(candidate):
            return numeric_tokens
        merged.append(candidate)
    return merged


# A THIRD, DIFFERENT real pdfplumber artifact, found live (18 Aug 2026)
# against Nations Trust Bank PLC's (NTB.N0000) real interim statement for
# the six months ended 30 June 2026: bold-rendered text on several pages
# comes out with every character glyph doubled, e.g. page 4's own title
# literally extracts as
#   "SSTTAATTEEMMEENNTT OOFF FFIINNAANNCCIIAALL PPOOSSIITTIIOONN"
# instead of "STATEMENT OF FINANCIAL POSITION" — most likely a "faux
# bold" rendering where the PDF draws the same glyph twice at a near-
# identical position and pdfplumber's own text-reconstruction reads both
# as separate characters. Confirmed by hand: indexing only the letter
# run's own characters (`"SSTTAATTEEMMEENNTT"[0::2] == "STATEMENT"`)
# recovers the real word exactly. Left unrepaired, this page's own title
# never matches `_STATEMENT_PAGE_MARKERS`
# (app.ingestion.financial_pdf_extractor) and its own "LKR '000" unit
# declaration never matches `_UNIT_THOUSANDS_RE` above either (the
# doubled "LLKKRR" does not contain the substring "lkr") — the whole page
# was silently skipped, 0 drafts, despite carrying NTB's real newest-
# quarter balance sheet.
#
# CONFIRMED NOT UNIFORM ACROSS THE PAGE, LET ALONE THE DOCUMENT. The same
# real page's own body rows are NOT doubled — "Cash and Cash Equivalents
# 37,873,231 19,864,631" reads perfectly normally right next to a doubled
# "TToottaall AAsssseettss" subtotal row two lines below it — and the very next
# real statement page in the same PDF (page 6, "STATEMENT OF CASH FLOWS")
# is not doubled at all. This matches a bold/non-bold rendering split
# (titles and subtotal rows are typically bold on these statements, body
# rows are not), which means detection CANNOT be a single whole-page or
# whole-document yes/no decision — it has to work per RUN (per
# whitespace-delimited token), exactly like `_repair_split_leading_digits`
# above already works per-token rather than per-line.
#
# THE PER-TOKEN TEST ITSELF IS DELIBERATELY STRICT, TO AVOID A REAL FALSE-
# POSITIVE RISK: a genuinely doubled token has EVERY character glyph
# repeated, i.e. `token[2i] == token[2i+1]` for every position — the same
# "de-duplicate then re-double reproduces the original exactly" round-trip
# described by the real finding above. A coincidentally-repeated-looking
# real token (e.g. a real "COMMITTEE" or "OFFICE" heading elsewhere in a
# normal, non-buggy annual report) almost never satisfies this for its
# FULL length — verified against every real fixture already in
# test_financial_statement_parsing.py (BALANCE_SHEET_TEXT,
# BALANCE_SHEET_TEXT_SWAD, BALANCE_SHEET_TEXT_AHPL and the two real income/
# cash-flow statement texts): none of them contain a single token this
# test misfires on, and neither does "COMMITTEE"/"OFFICE"/"ANNOUNCEMENT"/
# "NOMINATION" tested standalone. `_MIN_DOUBLED_RUN_LEN` additionally
# requires at least 4 characters (i.e. a real de-doubled length of at
# least 2), specifically to rule out a real, short, coincidentally-
# repeated-digit token (a percentage like "22" meaning literally 22%, not
# a doubled "2") from being misread as doubled in isolation.
#
# A PER-TOKEN TEST ALONE IS STILL NOT ENOUGH, THOUGH — applying it to
# EVERY token on EVERY page, unconditionally, would still risk quietly
# halving a genuine short coincidentally-doubled value on a normal,
# non-buggy filing (e.g. a real unformatted 4-digit count like "5500").
# So this is additionally GATED per page: the transform only runs at all
# when the page's own text contains a line with at least two INDEPENDENT
# long (>=8 character) tokens that both pass the strict round-trip test —
# in practice, this is the page's own multi-word statement title, which
# is always present and always long on a real primary statement page, and
# is a signal a short coincidental value could not plausibly produce by
# chance. A normal page's title is never doubled, so the gate never fires
# there, and every token on it — however coincidentally "repeated" it
# might look in isolation — is left completely untouched.
_MIN_DOUBLED_RUN_LEN = 4


def _is_doubled_run(token: str) -> bool:
    """True only if `token` round-trips exactly as a doubled run: every
    character glyph repeated back-to-back, the whole way through. See the
    module comment above this constant for why this has to be this strict
    to avoid misreading a real, short, coincidentally-repeated value."""
    if len(token) < _MIN_DOUBLED_RUN_LEN or len(token) % 2 != 0:
        return False
    return all(token[i] == token[i + 1] for i in range(0, len(token), 2))


def _page_looks_character_doubled(page_text: str) -> bool:
    """The page-level gate — see the module comment above
    `_MIN_DOUBLED_RUN_LEN` for why a per-token test alone isn't a safe
    enough signal on its own."""
    for line in page_text.splitlines():
        long_doubled_words = [
            word for word in line.split() if len(word) >= 8 and _is_doubled_run(word)
        ]
        if len(long_doubled_words) >= 2:
            return True
    return False


def repair_character_doubling(page_text: str) -> str:
    """Real, narrowly-scoped fix for the NTB.N0000 character-doubling
    artifact described above. A no-op (`page_text` returned byte-
    identical) unless `_page_looks_character_doubled` finds strong
    evidence THIS page is affected; when it does, every individual token
    that itself round-trips as a doubled run is de-doubled (via
    `token[0::2]`, keeping only its own alternating characters), and every
    token that doesn't (a normal, non-doubled word or a value split by an
    unrelated pdfplumber spacing artifact) is left exactly as printed.
    Rejoins each line's tokens with a single space, matching what every
    downstream consumer (`_is_primary_statement_page`, `detect_unit_scale`,
    `extract_candidate_lines`, all of which already normalise internal
    whitespace via `.split()`/`\\s+`) already assumes."""
    if not _page_looks_character_doubled(page_text):
        return page_text
    repaired_lines = []
    for line in page_text.splitlines():
        tokens = line.split()
        repaired_lines.append(
            " ".join(token[0::2] if _is_doubled_run(token) else token for token in tokens)
        )
    return "\n".join(repaired_lines)


# CSE comparative statements consistently print exactly this many value
# columns (Group this-year, Group last-year, Company this-year, Company
# last-year — verified on J.F. Packaging PLC, whose own column header
# reads "Notes Rs.000 Rs.000 Rs.000 Rs.000"). This is the signal used to
# tell a leading note-reference token apart from a genuine value: "5" and
# "13.2" are indistinguishable from real values by shape alone (a note
# ref and a small value/a decimal EPS figure can look identical), but a
# line with 5 numeric tokens when exactly 4 are expected almost certainly
# has a note reference in the extra slot. Used only as a FALLBACK now —
# see `detect_expected_value_columns` below for the real per-page count,
# read from the page's own header rather than assumed.
DEFAULT_EXPECTED_VALUE_COLUMNS = 4

# Matches a bare 4-digit year, 1900-2099 — deliberately NOT anchored to a
# specific date format (CSE filings write the same header date as
# "31st March 2026", "30-06-2026", "30.06.2026", or just a bare "2026"
# repeated once per column with the day/month stated only once), since
# every one of those shapes still leaves the actual YEAR as a standalone
# token that survives normal whitespace tokenisation. A thousands-grouped
# monetary figure never collides with this: a comma inside a real value
# (e.g. "1,025,218") breaks the token into pieces at each comma, so no
# 4-digit run ever sits at a token's own start/end boundary the way a
# genuine year does.
_YEAR_TOKEN_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

# A Sri Lankan fiscal-year RANGE label ("2019/2020" — the SL fiscal year
# runs April-March, so a filing routinely writes it as two calendar years
# joined by a slash) is ONE column's own header, not two. REAL BUG THIS
# CLOSES, found live (27 Aug 2026) tracing a currently-live note-
# reference-as-value corruption on Asia Asset Finance PLC's real FY2019/20
# annual report: its Statement of Cash Flows header reads "2019/2020
# 2018/2019" for a genuinely 2-column (current/prior year) statement, but
# `_YEAR_TOKEN_RE.findall` alone finds FOUR bare 4-digit runs on that one
# line (2019, 2020, 2018, 2019) — double-counting each range label as two
# columns instead of one — so `detect_expected_value_columns` returned 4
# instead of 2, silently falling back to `DEFAULT_EXPECTED_VALUE_COLUMNS`
# behaviour and letting a genuine 3-numeric-token line ("Acquisition of
# property, plant and equipment 20 (27,787,206) (57,293,522)" — note ref
# "20" + 2 real values) pass the `len(numeric_tokens) > expected_value_
# columns` check as 3 > 4 = False, so the note reference "20" was kept as
# the real value instead of correctly dropped.
_YEAR_RANGE_TOKEN_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}/(?:19|20)\d{2}(?!\d)")


def _count_year_tokens(line: str) -> int:
    """Counts year-shaped column headers on one line, treating a
    `_YEAR_RANGE_TOKEN_RE` match as ONE column (not two) — see that
    constant's own docstring for the real corruption this closes. Range
    matches are found and removed FIRST so their own two constituent
    4-digit runs are never also counted by the plain single-year pattern
    afterward; every remaining bare year (J.F. Packaging's real "2026
    2025 2026 2025" plain-calendar-year style, still one column each) is
    then counted exactly as before — this function changes nothing for a
    filing that has no `YYYY/YYYY` range label anywhere.

    An immediately-ADJACENT literal duplicate (the exact same 4-digit
    year, separated from the next match by nothing but whitespace) counts
    as ONE column, not two. REAL BUG THIS CLOSES, found live (28 Aug 2026)
    tracing Ownally Holdings PLC's real confirmed `revenue` stored as the
    literal digit "6": its real income statement header reads "Year ended
    31 March 2022 2022 2021" — a genuinely 2-column (2022/2021) statement
    — but pdfplumber has merged the page's title line ("...ended 31 March
    2022", whose own trailing year is simply completing that sentence, not
    naming a data column) with the table's real header row ("2022 2021")
    onto one line of text. J.F. Packaging's real "2026 2025 2026 2025"
    proves a repeated year is normally exactly as many real columns as
    times it's printed — no year there is an adjacent literal duplicate of
    its immediate neighbour — so this narrow, position-aware collapse
    (only two IDENTICAL year tokens with nothing between them) changes
    nothing for that shape while fixing Ownally's: "2022 2022 2021" counts
    as 2 (the second "2022" collapses into the first), matching the real
    2 value columns instead of the naive 3."""
    ranges = _YEAR_RANGE_TOKEN_RE.findall(line)
    # Blanked out with a non-whitespace filler (not a plain " ") so two
    # bare years that were only adjacent BECAUSE a range sat between them
    # in the original line ("2019/2020 2025 2018/2019 2025" — the two
    # "2025"s are genuinely distinct columns) don't get mistaken by the
    # adjacency check below for a real, position-preserving duplicate —
    # the filler still breaks up the line the same way the range itself
    # did, just without contributing its own year-shaped digits.
    remainder = _YEAR_RANGE_TOKEN_RE.sub(lambda m: "#" * len(m.group()), line)
    count = 0
    prev_match = None
    for m in _YEAR_TOKEN_RE.finditer(remainder):
        if (
            prev_match is not None
            and m.group() == prev_match.group()
            and remainder[prev_match.end() : m.start()].strip() == ""
        ):
            continue  # adjacent literal duplicate — see docstring
        count += 1
        prev_match = m
    return len(ranges) + count

# The unit declaration, counted per OCCURRENCE rather than merely
# detected once (unlike `_UNIT_THOUSANDS_RE`/`_UNIT_FULL_VALUE_RE` above,
# which only ever need a yes/no answer for scale) — real filings that
# repeat their unit once per column (verified: J.F. Packaging's "Notes
# Rs.000 Rs.000 Rs.000 Rs.000", eChannelling's "LKR LKR") give a real,
# reliable column count this way; ones that state it once for the whole
# page (verified: AHPL's "In Rs.'000s Note") don't, which is fine — that
# case is exactly what `_YEAR_TOKEN_RE` above is for instead.
_UNIT_TOKEN_RE = re.compile(r"\b(?:rs\.?|lkr)\s*(?:['’]?\s*000s?)?", re.IGNORECASE)

#: How many of the page's own header lines (from the top) to search for
#: the real column-count signal — verified generous enough for every real
#: fixture this module has (title/company-name lines, "STATEMENT OF...",
#: "GROUP COMPANY", then the date row, all within the first ~6 lines on
#: every filing checked), without scanning so far down the page that a
#: coincidental 4-digit figure or "%" in the actual DATA rows gets
#: mistaken for a header.
_HEADER_SEARCH_LINES = 10


def detect_expected_value_columns(page_text: str) -> int | None:
    """How many real value columns this specific page's statement uses —
    read from the page's OWN header rather than assumed to always be 4.

    REAL BUG THIS CLOSES, FOUND LIVE (20 Aug 2026): `DEFAULT_EXPECTED_
    VALUE_COLUMNS`'s own "KNOWN LIMITATION" comment named this gap
    without fixing it — a company whose real filing isn't a 4-column
    Group/Company comparative silently got the wrong expected count,
    which corrupts the "how many numeric tokens are genuinely excess"
    signal `split_label_and_values` depends on. Confirmed on 4 REAL,
    INDEPENDENT filings the same day:

      - eChannelling PLC's real interim statement is a genuine 2-column
        (current period / prior period) single-entity layout with no
        Group/Company split at all — its own header reads "As at
        30.06.2026 31.12.2025", two dates, not four.
      - Tea Smallholder Factories PLC's real income statement is a
        genuine 3-column layout (current quarter / prior-year quarter /
        change), with the change column its own separate "%"-headed
        slot ("RS. '000 RS. '000 %") rather than a fourth Group/Company
        comparative.

    Both silently corrupted their own real "Total Liabilities"/"Revenue"-
    style lines under the assumed default of 4.

    Two independent signals, both counted per line, MAX taken across
    BOTH signals and every one of the page's first `_HEADER_SEARCH_LINES`
    lines:

      - year-like tokens (`_count_year_tokens`, built on `_YEAR_TOKEN_RE`)
        — real filings repeat the year once per real value column in
        their own date header. A `YYYY/YYYY` fiscal-year-RANGE label
        (Asia Asset Finance PLC's real "2019/2020 2018/2019" — see
        `_YEAR_RANGE_TOKEN_RE`'s own docstring for the live corruption
        this closes) counts as ONE column, not two.
      - unit-declaration occurrences (`_UNIT_TOKEN_RE`) PLUS bare "%"
        markers on that SAME line — covers both the common case (the
        unit repeated once per column, e.g. eChannelling's "LKR LKR")
        and Tea Smallholder's own shape (2 monetary columns, each with
        its own "RS.'000", plus one separate non-monetary "%" column the
        year-only signal alone can't see).

    Verified against every real fixture this module already had (J.F.
    Packaging, Swadeshi, AHPL, PAP, LWL) — every one counts to exactly 4
    either way, matching `DEFAULT_EXPECTED_VALUE_COLUMNS` precisely, so
    detecting this changes NOTHING for any of them — as well as the
    other real filings named above (eChannelling: 2; Muller & Phipps,
    Swisstek: 4 each; Tea Smallholder: 3; Asia Asset Finance: 2, the
    fiscal-year-range case `_count_year_tokens` exists for).

    Returns `None` — never a guessed count — when the best line found
    scores below 2: a single stray year or unit mention isn't a reliable
    signal, and callers should fall back to `DEFAULT_EXPECTED_VALUE_
    COLUMNS` in that case exactly as they always have.
    """
    best = 0
    for line in page_text.splitlines()[:_HEADER_SEARCH_LINES]:
        year_count = _count_year_tokens(line)
        unit_count = len(_UNIT_TOKEN_RE.findall(line)) + line.count("%")
        # A bare "%" variance column can share the YEAR/date line itself
        # instead of the unit-declaration line — REAL BUG THIS CLOSES,
        # found live (28 Aug 2026) tracing Chemanex PLC's real confirmed
        # `revenue`: its header reads "2018 2017 Variance %" (years and
        # the "%" together) on one line, then "(In Rs. '000) Note" (a
        # single, non-repeated unit declaration — AHPL's already-known
        # shape) on another. `unit_count` alone is only 1 there (one
        # bare "%", no "Rs."/"LKR" on that same line), so `max(year_
        # count, unit_count)` picked year_count=2 and lost the real 3rd
        # column entirely — a different line arrangement of the exact
        # same 3-column shape `_HEADER_SEARCH_LINES`'s own Tea
        # Smallholder case already handles (there the "%" shares the
        # UNIT line instead, already summed into `unit_count`). Adding
        # the two signals together when they cooccur on the SAME year
        # line closes this without touching Tea Smallholder's case at
        # all (unaffected — its year line carries no "%") or any 4-
        # column fixture (none has a "%" on its own year line).
        year_and_percent = year_count + line.count("%") if year_count > 0 else 0
        best = max(best, year_count, unit_count, year_and_percent)
    return best if best >= 2 else None

# Canonical statement-line key -> exact normalised label text(s) that map
# to it. Deliberately EXACT match (post-normalisation), not substring —
# "total assets" must never match "total non-current assets". Verified
# against J.F. Packaging PLC's FY2025/26 statements; expand as more real
# filings are processed rather than guessing at wording variance across
# the ~286 listed companies up front.
CANONICAL_LABELS: dict[str, tuple[str, ...]] = {
    "total_assets": ("total assets",),
    "total_current_assets": ("total current assets",),
    "total_non_current_assets": ("total non-current assets", "total non current assets"),
    "total_equity": (
        "total equity",
        "total shareholders funds",
        "total shareholders' funds",
        # Nations Trust Bank PLC's real interim statement for the six
        # months ended 30 June 2026 — verified after fixing the real
        # character-doubling extraction artifact on its own balance-sheet
        # page (see `repair_character_doubling`'s docstring): the
        # de-doubled label reads "Total Shareholders' Equity", a real
        # third wording distinct from both variants above.
        "total shareholders' equity",
    ),
    # The equity that belongs to the LISTED company's own shareholders —
    # `total_equity` on a group balance sheet also includes the
    # non-controlling (minority) interest in partly-owned subsidiaries,
    # which for a holding company can be a large fraction of the total
    # (LOLC Holdings: ~40%). Per-share book value for a valuation must sit
    # on this line, not `total_equity`. Matched by longest phrase first
    # so "total equity attributable to owners" doesn't fall through to
    # the bare "total equity" alias above.
    "equity_attributable_to_owners": (
        "equity attributable to owners of the company",
        "equity attributable to owners of the parent",
        "equity attributable to equity holders of the company",
        "equity attributable to equity holders of the parent",
        "equity attributable to shareholders of the company",
        "total equity attributable to owners of the company",
        "total equity attributable to equity holders of the parent",
        "attributable to equity holders of the parent",
        "attributable to owners of the company",
    ),
    "non_controlling_interest": (
        "non-controlling interest",
        "non-controlling interests",
        "non controlling interest",
        "non controlling interests",
        "minority interest",
        "minority interests",
    ),
    "total_liabilities": ("total liabilities",),
    "total_current_liabilities": ("total current liabilities",),
    "total_non_current_liabilities": ("total non-current liabilities", "total non current liabilities"),
    "total_equity_and_liabilities": ("total equity and liabilities",),
    "revenue": (
        "revenue",
        "turnover",
        # Hikkaduwa Beach Resort PLC's real interim statement for the
        # quarter ended 30 June 2026 — the standard IFRS 15 contract-
        # revenue wording, likely to recur across many CSE filings, not
        # a one-off.
        "revenue from contracts with customers",
    ),
    "cost_of_sales": ("cost of sales",),
    "gross_profit": (
        "gross profit",
        # Tea Smallholder Factories PLC's real interim statement for the
        # quarter ended 30 June 2026 — the loss-period alternative carried
        # inline in the label itself, the same pattern income_tax_
        # expense's own "income tax (expense) / reversal" variant below
        # already established for a different line.
        "gross profit / (loss)",
    ),
    # "results from operating activities" is the standard IFRS wording on
    # CSE filings and was the single biggest extraction gap in the system:
    # `operating_profit` was missing for 227 of 283 tickers, which alone
    # blocked §18's DCF. Verified on three independent real filings
    # (JKH.N0000 p9/p15, KHL.N0000 p3/p8, CCS.N0000 p2, all July 2026
    # interims). Matching is an exact lookup on the normalised label, so
    # the neighbouring "other operating income"/"other operating expenses"
    # lines on those same pages cannot collide with it.
    #
    # The variants below were measured the same way as
    # `capital_expenditure`'s (see that key's comment for the method).
    #
    # Deliberately EXCLUDED, and these matter more than the additions:
    #   - "other operating income" (28 companies, the single most common
    #     unmatched label near this line) is a REVENUE COMPONENT sitting
    #     a few rows above operating profit, not a subtotal. Matching it
    #     would put a small income line into every DCF as if it were EBIT.
    #   - "operating profit/(loss) before working capital changes" (7)
    #     and "operating profit before changes in operating assets and
    #     liabilities" (2) are the CASH-FLOW statement's opening subtotal,
    #     a different figure entirely — they are added to
    #     `operating_profit_before_working_capital_changes` below instead.
    #   - "total operating income" (1) is a financial-firm line, and
    #     financials are correctly never routed to an FCFF DCF.
    #   - "profit before tax from continuing operations" and its
    #     relatives are PBT, already a different canonical key.
    #   - "profit/(loss) from operations after net finance expense" is
    #     AFTER finance costs, so it is not EBIT.
    "operating_profit": (
        "operating profit",
        "results from operating activities",
        "profit from operations",  # 13 companies
        "profit from operating activities",  # 6
        "profit/(loss) from operations",  # 3
        "profit / (loss) from operations",  # 3
        "profit/ (loss) from operating activities",  # 2
        "operating profit/ (loss)",  # 2
        "operating profit / (loss)",
        "operating profit/(loss)",
    ),
    # "profit before taxation" is the same figure spelled the longer way
    # on 21 of the 130 filings measured — see `capital_expenditure`'s
    # comment for the method. PBT drives the effective tax rate §18's DCF
    # and WACC's cost of debt both need, so this wording being unmatched
    # was blocking those for every company that uses it.
    "profit_before_tax": ("profit before tax", "profit before taxation"),
    "income_tax_expense": (
        "income tax expense",
        # Swadeshi Industrial Works PLC's real FY2025/26 income statement
        # (17 Aug) — the line's own printed wording carries the
        # loss-period alternative inline rather than as a separate line,
        # unlike every other canonical key's variants seen so far. Found
        # live: without this, `income_tax_expense` — and therefore
        # `effective_tax_rate` and every model that needs it (DCF, WACC's
        # cost of debt) — silently failed to extract for this real
        # filing despite every other required DCF input succeeding.
        "income tax (expense) / reversal",
    ),
    "net_income": ("profit for the year", "profit for the period"),
    "total_comprehensive_income": ("total comprehensive income for the year", "total comprehensive income for the period"),
    # Cash-flow-statement lines — verified against TWO real, independent
    # filings: J.F. Packaging PLC's FY2025/26 statement of cash flow
    # (first) and Swadeshi Industrial Works PLC's FY2025/26 statement of
    # cash flows (second, 17 Aug — deliberately sought out to check
    # whether one company's wording generalised, per this file's own
    # "expand as more real filings are processed rather than guessing"
    # rule). It did NOT: every one of these four line concepts is worded
    # completely differently between the two companies — proof this
    # discipline is load-bearing, not decorative. See
    # _STATEMENT_PAGE_MARKERS in app.ingestion.financial_pdf_extractor,
    # and PARAMETERS.md #9's history of this gap. "Cash generated from/
    # (Used in) Operations" (JFP) is the pre-tax, pre-interest subtotal —
    # a real, differently-named line on the same statement — and is
    # deliberately NOT mapped to `cash_flow_from_operations`, which is
    # the figure after tax and interest paid, the one `app.domain.
    # ratios`' cash-flow ratios and §18's FCFF both mean by "CFO."
    # Named `cash_flow_from_operations` to match the key
    # `app.domain.ratios.NOT_YET_COMPUTABLE` has used since Phase 2 for
    # this exact concept, rather than inventing a second name for the
    # same figure across the two modules.
    "cash_flow_from_operations": (
        "net cash flow from/ (used in) operating activities",  # JFP
        "net cash from / used in operating activities",  # SWAD
    ),
    "net_cash_from_investing_activities": (
        "net cash flow generated from / (used in) investing activities",  # JFP
        "net cash flows (used in) / from investing activities",  # SWAD
    ),
    "net_cash_from_financing_activities": (
        "net cash flow generated from / (used in) financing activities",  # JFP
        "net cash flows from /(used in) financing activities",  # SWAD
    ),
    "net_increase_in_cash": (
        "net increase/(decrease) in cash & cash equivalents during the year",  # JFP
        "net (decrease) / increase in cash and cash equivalents",  # SWAD
    ),
    # Combined D&A on one line, verified on J.F. Packaging PLC. Swadeshi
    # Industrial Works PLC reports "Depreciation" and "Amortization" as
    # two SEPARATE lines instead — `depreciation_expense` and
    # `amortisation_expense` below capture those individually, and
    # `derive_combined_depreciation_and_amortisation` sums them into this
    # same canonical concept when the combined line itself isn't present,
    # so the two wordings converge on one figure rather than needing every
    # caller to know which shape a given company uses.
    "depreciation_and_amortisation": ("depreciation / amortization",),  # JFP
    # Verified on Swadeshi Industrial Works PLC only, and deliberately
    # scoped to statement pages (_STATEMENT_PAGE_MARKERS) — a bare
    # "Depreciation" is common enough wording that matching it outside
    # the primary statements (e.g. a PP&E movement note) would be a real
    # false-positive risk; on the cash-flow-statement page specifically
    # it has never meant anything else in either filing checked so far.
    # "depreciation of property, plant and equipment" verified on
    # JKH.N0000 p13 and KHL.N0000 p6. Those filings ALSO print a separate
    # "depreciation of right-of-use assets" line, which first-occurrence-
    # wins does not add in; that understates D&A, which understates FCFF
    # and therefore fair value — the safe direction — and summing across
    # occurrences is deliberately not done here because the same labels
    # reappear on segment-note pages and would double-count.
    "depreciation_expense": ("depreciation", "depreciation of property, plant and equipment"),  # SWAD
    # "amortisation of intangible assets" verified on JKH.N0000 p13 and
    # KHL.N0000 p6 (both also carry an ROU-amortisation line — same
    # safe-direction note as depreciation_expense above).
    "amortisation_expense": ("amortization", "amortisation of intangible assets"),  # SWAD
    # Capital expenditure — genuinely NEW as of this filing. J.F.
    # Packaging PLC's equivalent label ("Purchase & Construction of
    # Property, Plant & Equipment & Intangible Assets") wraps across two
    # physical lines on that statement and was left unmapped for exactly
    # that reason (see this module's earlier commit); Swadeshi's shorter
    # label doesn't wrap, so this key is extractable for at least this
    # wording. PP&E only — Swadeshi reports "Acquisition of Intangible
    # Assets" as a separate, smaller line this key deliberately excludes,
    # so a company with material intangible capex will read slightly
    # low here, a real, stated incompleteness rather than a silent one.
    # "purchase and construction of property, plant and equipment" is the
    # real cash-flow wording on both JKH.N0000 (p12) and KHL.N0000 (p6) —
    # neither uses the "acquisition of..." form this list started with.
    # capital_expenditure was missing for 215 of 283 tickers.
    # The wordings below were MEASURED, not guessed, by
    # `scripts/measure_unmatched_labels.py`: it re-parsed 130 real
    # non-financial filings already on file, collected every label that
    # parsed as a line item on a primary-statement page but matched no
    # canonical key, and ranked them by how many DISTINCT companies print
    # them. Counts in comments are that measurement. The long tail is
    # mostly punctuation and pluralisation drift around the same three
    # words ("&" vs "and", "equipments", a stray space before the comma),
    # which exact-match cannot absorb and which is why this line was
    # missing for 113 of 177 non-financial tickers.
    #
    # Deliberately EXCLUDED, having been looked at:
    #   - "acquisition of investment property" / "acquisition of
    #     intangible assets and capital work-in-progress" — real lines,
    #     but neither is PP&E, and this key is PP&E (see below).
    #   - "disposal / (acquisition) of property, plant and equipment..."
    #     — the sign depends on which way that filing nets it out.
    #   - "additions of mature and immature plantations net of sale of
    #     timber" — net of disposals, so not gross capex.
    #
    # PP&E only, unchanged from this key's original scope: a company with
    # material intangible capex reads slightly low here. NOTE that this
    # understates capex, which OVERSTATES FCFF and therefore fair value —
    # the unsafe direction, and the one real caveat on this key. It is
    # kept only because changing the key's meaning is a separate decision
    # from fixing its coverage; the compound "...& intangible assets"
    # wordings are left unmatched rather than silently widening it.
    "capital_expenditure": (
        "acquisition of property, plant and equipment",  # SWAD
        "purchase and construction of property, plant and equipment",
        "purchase of property, plant and equipment",  # 11 companies
        "acquisition of property, plant & equipment",  # 9
        "purchase of property, plant & equipment",  # 6
        "purchase and construction of property, plant & equipment",  # 3
        "acquisition and construction of property, plant and equipment",  # 3
        "purchase of property, plant & equipments",  # 2
        "purchase & construction of property, plant & equipment",  # 2
        "acquisition of property , plant & equipment",  # 2 (space before comma)
        "purchases of property, plant and equipment",
        "purchase of property plant and equipment",
        "purchase of property and equipment",
        "purchase and constructions of property, plant & equipment",
        "acquisition of property plant & equipment",
        "acquisition of property,plant,equipment",
        "acquisition of property, plant & equipments",
        "additions to property, plant & equipment",
        "addition to property, plant & equipment",
        "capital expenditure",
    ),
    # The two bookend subtotals of the operating-activities working-
    # capital section — verified on BOTH real filings, and the reason
    # `change_in_net_working_capital` below can be derived at all without
    # summing an unpredictable, company-varying set of component lines
    # (J.F. Packaging lists 5 such lines — inventories, receivables,
    # payables, amounts due from/to related parties; Swadeshi lists 4
    # differently-named ones — inventories, receivables, advances and
    # prepayments, payables). "Operating Profit before Working Capital
    # Changes" is worded byte-identically on both companies' statements,
    # a genuine, confirmed reusable label rather than one that happened
    # to match once. "Cash generated from Operations" (the subtotal AFTER
    # working-capital movements, BEFORE tax and interest — the same line
    # `cash_flow_from_operations`'s own docstring already distinguishes
    # from CFO) needed a second wording, same as every other cash-flow
    # line here.
    # The loss-period and "operating assets and liabilities" variants
    # below are the same measured sweep as `operating_profit`'s, and are
    # the wordings deliberately kept OUT of that key (see its comment) —
    # this is the line they actually belong to. Both bookends feed
    # `change_in_net_working_capital`, and so §18's FCFF.
    "operating_profit_before_working_capital_changes": (
        "operating profit before working capital changes",  # JFP + SWAD, identical
        "operating profit/(loss) before working capital changes",  # 7 companies
        "operating profit / (loss) before working capital changes",  # 2
        "operating profit before changes in operating assets and liabilities",  # 2
    ),
    "cash_generated_from_operations": (
        "cash generated from/ (used in) operations",  # JFP
        "cash generated from operations",  # SWAD
        "cash (used in) / generated from operations",  # 2
        "cash generated from / (used in) operations",  # 2
    ),
    # WACC's cost-of-debt input — verified on Swadeshi Industrial Works
    # PLC's real balance sheet, where "Interest Bearing Loans and
    # Borrowings" prints TWICE, byte-identically, once under Non-current
    # Liabilities (11,672,993) and once under Current Liabilities
    # (634,163,111) — the standard maturity-split presentation for one
    # debt figure. See `SUM_ACROSS_OCCURRENCES` below: this key is
    # deliberately summed across every match on the statement rather
    # than keeping only the first (which would silently keep the smaller
    # non-current portion and drop the much larger current one).
    "total_interest_bearing_debt": (
        "interest bearing loans and borrowings",  # SWAD
        "interest bearing borrowings",  # JFP — ALSO prints twice, same reason
    ),
    # The cash-flow statement's own interest-expense figure — the
    # non-cash add-back line, not "... Paid" (a real, differently-worded
    # line on the same statement, the cash actually disbursed, which is
    # NOT what a WACC cost-of-debt calculation wants — that wants the
    # period's expense, whether or not it was paid in cash this period).
    "interest_expense": (
        "finance costs",  # SWAD
        "interest expense",  # JFP — same cash-flow-statement accrual add-back concept
    ),
    # Working-capital STOCK components (§18's `working_capital_pct_
    # revenue`) — verified on BOTH real balance sheets, where "Inventories",
    # "Trade and Other Receivables" and "Trade and Other Payables" are
    # byte-identical wording across both companies. Neither company's
    # component SET is complete on its own — J.F. Packaging breaks out
    # related-party amounts Swadeshi doesn't have; Swadeshi has "Advances
    # and Prepayments" J.F. Packaging doesn't — which is exactly why
    # `derive_net_working_capital` below sums WHICHEVER of these are
    # present for a given company rather than requiring all of them.
    # Cross-checked against each statement's own totals: (Total Current
    # Assets - Cash - tax/other non-operating items) and (Total Current
    # Liabilities - debt - tax) both equal the sum of exactly these
    # components on both real filings, confirming this is the right set
    # rather than an arbitrary one.
    "inventories": ("inventories",),  # JFP + SWAD, identical
    "trade_receivables": ("trade and other receivables",),  # JFP + SWAD, identical
    "trade_payables": ("trade and other payables",),  # JFP + SWAD, identical
    # ---- §24's balance-sheet set, measured the same way as
    # `capital_expenditure`'s wordings (see that key's comment). NONE of
    # these five had a canonical key at all before, which is why the
    # canonical metrics layer could not compute net debt, tangible
    # equity, FCFE or Altman Z for ANY company: `cash` simply did not
    # exist as a concept in this pipeline.
    #
    # `cash_and_cash_equivalents`: the plain wording also appears at the
    # FOOT of the cash-flow statement, but the balance sheet precedes it
    # in every filing shape seen, and first-occurrence-wins therefore
    # takes the balance-sheet figure — which is the one §24 means by
    # "cash". The cash-flow statement's own opening/closing lines carry
    # their own longer wordings ("...at the beginning of the period"),
    # so they cannot collide with this.
    "cash_and_cash_equivalents": (
        "cash and cash equivalents",  # 53 companies
        "cash & cash equivalents",  # 18
        "cash in hand and at bank",  # 15
        "cash and bank balances",  # 8
        "cash & bank balances",  # 7
        "cash in hand & bank",  # 4
        "cash in hand & at bank",  # 4
        "cash in hand",  # 3
    ),
    # Overdrafts are borrowings, not negative cash: net debt has to add
    # them back. Kept as their own key rather than folded into
    # `total_interest_bearing_debt`, because on these filings the
    # overdraft sits in current liabilities SEPARATELY from the borrowing
    # lines that key already matches, and summing them here would double
    # count for any company whose debt line already includes it.
    "bank_overdraft": (
        "bank overdraft",  # 47
        "bank overdrafts",  # 35
    ),
    "property_plant_and_equipment": (
        "property, plant and equipment",  # 45
        "property, plant & equipment",  # 36
        "property,plant and equipment",  # 2
        "property plant and equipment",
        "property plant & equipment",
    ),
    # Tangible equity = total_equity - intangible_assets, so this is the
    # input §24's "tangible equity" needs.
    "intangible_assets": (
        "intangible assets",  # 68
        "intangible asset",
    ),
    "investment_property": (
        "investment property",  # 26
        "investment properties",  # 19
    ),
    "advances_and_prepayments": ("advances and prepayments",),  # SWAD
    "amounts_due_from_related_parties_trade": ("amounts due from related parties - trade",),  # JFP
    "amounts_due_from_related_parties_non_trade": ("amounts due from related parties - non trade",),  # JFP
    "amounts_due_to_related_parties_trade": ("amounts due to related parties - trade",),  # JFP
    "amounts_due_to_related_parties_non_trade": ("amounts due to related parties - non trade",),  # JFP
    # §22 rule 1's hard-book input — verified against FOUR real filings,
    # deliberately sought out in the sector §22 itself names ("plantations,
    # property and hotels"), and genuinely NOT one consistent shape.
    # Kelani Valley Plantations PLC's real Statement of Financial Position
    # has NO revaluation-related equity line at all — real, verified,
    # zero-nonzero evidence, not an extraction gap: Sri Lanka's regional
    # plantation companies (KVPL among them) hold estate land on 99-year
    # GOVERNMENT LEASES from the 1992 privatisation, not freehold, so
    # freehold PP&E/bearer biological assets are carried at cost, and
    # there is nothing to revalue. Asian Hotels and Properties PLC (owns
    # Cinnamon Grand Colombo) prints a single COMBINED line instead,
    # "Other components of equity" — CORRECTED 17 Aug, re-verified
    # directly against the actual currently-public filing after an
    # earlier version of this comment cited a later FY2025/26 report and
    # figures that could not be found or reproduced: AHPL's real FY2023/24
    # Statement of Financial Position (page 164, downloaded fresh from
    # `https://cdn.cse.lk/cmt/upload_report_file/690_1716340840640.pdf`)
    # prints "Other components of equity 23 21,752,125 20,613,338
    # 21,142,080 20,112,228" — extracted end-to-end through the real
    # pipeline (`extract_financial_statement_candidates`) without a
    # notes-page or double-count issue. Its own Statement of Changes in
    # Equity/Note 23 (a differently-shaped, multi-reserve-column statement
    # this extractor cannot parse — see below) breaks the combined figure
    # down into a Revaluation Reserve plus a smaller Other Capital
    # Reserve, confirming the combined line is REVALUATION-DOMINATED for
    # this company but is NOT a pure revaluation-reserve figure — used
    # here as the best genuinely available real proxy, never silently
    # presented as an exact revaluation figure (see `app.domain.
    # valuation_view.hard_book_for`'s own docstring). Galadari
    # Hotels (Lanka) PLC's real FY2025 Statement of Financial Position
    # prints a genuinely PURE, standalone "Revaluation reserve" line
    # (6,454,099,241) — no bundling at all — but that filing's statement is
    # two-column (2025/2024 only, no Group/Company split), which this
    # extractor's note-reference-stripping heuristic does not yet handle
    # (see DEFAULT_EXPECTED_VALUE_COLUMNS's own "KNOWN LIMITATION" comment)
    # — added as a verified real wording for when a 4-column filing uses it,
    # but Galadari's OWN filing is not correctly end-to-end extractable
    # through this pipeline today, a pre-existing, separately-tracked gap,
    # not fixed here. Ceylon Hotels Corporation PLC and Serendib Hotels PLC
    # were also checked and bundle the same way AHPL does, but each under a
    # generic wording ("Reserves", "Other Components of Equity") too broad
    # or duplicative to add safely as further variants.
    # Deliberately NOT in SUM_ACROSS_OCCURRENCES below: unlike
    # total_interest_bearing_debt, a revaluation/other-components-of-
    # equity balance has no current/non-current maturity split to sum —
    # it is one number, printed once, on every real filing checked.
    "revaluation_reserves": (
        "other components of equity",  # AHPL — combined, revaluation-dominated proxy (verified end-to-end)
        "revaluation reserve",  # Galadari — pure, but not yet live-extractable (2-column filing)
    ),
    # §27's Altman Z"-Score needs retained_earnings/total_assets — the one
    # remaining input `ratios.NOT_YET_COMPUTABLE` still listed it as
    # missing for. Measured, not guessed, via `scripts/measure_unmatched_
    # labels.py`'s real sample of 130 real filings: "retained earnings"
    # printed by 62 distinct companies, "revenue reserves" (the same
    # concept under a different CSE-era naming convention) by 18 more —
    # both well past the "used by many companies" bar this project's own
    # standing rule applies before adding a wording.
    "retained_earnings": (
        "retained earnings",  # 62 companies
        "revenue reserves",  # 18 companies
    ),
    # A REAL, GENUINE third balance-sheet bucket, found live (18 Aug
    # 2026) on Lanka Walltiles PLC's (LWL.N0000) real interim statement
    # for the period ended 30 June 2026 — NOT an extraction bug. IFRS 5
    # requires assets of a disposal group classified as held for sale to
    # be presented SEPARATELY from ordinary current/non-current assets;
    # LWL's own real balance sheet does exactly that ("Assets held for
    # sale 366,082 277,606 - -", printed between "Total current assets"
    # and "Total assets", with a matching "Reserves of a disposal group
    # held for sale" equity line confirming a real disposal group exists
    # for this company). `total_assets` genuinely equals
    # `total_current_assets + total_non_current_assets +
    # assets_held_for_sale` on this real filing — the 366,082,000 gap
    # `check_accounting_identities`'s "assets = current + non-current"
    # check used to (correctly) flag was this real, third line item, not
    # a misread number. See that function's own comment for how this key
    # is used, and `liabilities_associated_with_assets_held_for_sale`
    # below for LWL's matching real liabilities-side line.
    "assets_held_for_sale": ("assets held for sale",),
    "liabilities_associated_with_assets_held_for_sale": (
        "liabilities associated with assets held for sale",
    ),
}

#: The working-capital STOCK's two sides — see `derive_net_working_
#: capital`. A company's own filing determines which of these are
#: actually present; summing "whichever apply" rather than requiring a
#: fixed set is what makes this generalise across two real filings with
#: genuinely different component breakdowns.
NET_WORKING_CAPITAL_ASSET_COMPONENTS: frozenset[str] = frozenset(
    {
        "inventories",
        "trade_receivables",
        "advances_and_prepayments",
        "amounts_due_from_related_parties_trade",
        "amounts_due_from_related_parties_non_trade",
    }
)
NET_WORKING_CAPITAL_LIABILITY_COMPONENTS: frozenset[str] = frozenset(
    {
        "trade_payables",
        "amounts_due_to_related_parties_trade",
        "amounts_due_to_related_parties_non_trade",
    }
)

#: Canonical keys where multiple occurrences on the same statement are
#: expected — the standard current/non-current maturity split for one
#: balance-sheet concept — and should be SUMMED into one figure rather
#: than the usual "first occurrence wins, the rest are dropped" rule
#: `build_fundamental_drafts` otherwise applies. Kept as an explicit
#: allowlist rather than a default behaviour, because most repeated
#: canonical matches on a real page ARE a bug worth catching (see
#: `build_fundamental_drafts`'s own "shouldn't happen given the page-
#: marker filter, but PDFs are messy" comment) — this set names the
#: specific, verified exception to that rule, not a blanket assumption
#: that a repeat is always fine to sum.
SUM_ACROSS_OCCURRENCES: frozenset[str] = frozenset({"total_interest_bearing_debt"})

_LABEL_TO_STATEMENT_LINE: dict[str, str] = {
    variant: key for key, variants in CANONICAL_LABELS.items() for variant in variants
}


def normalize_label(text: str) -> str:
    """Lowercase, collapse whitespace, strip a handful of decorations
    that appear in real headers but carry no meaning for matching (unit
    annotations, footnote markers)."""
    cleaned = text.strip().lower()
    cleaned = re.sub(r"\(rs\.?\s*'?000\)?", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -")


def match_canonical_label(label: str) -> str | None:
    return _LABEL_TO_STATEMENT_LINE.get(normalize_label(label))


# REAL BUG, FOUND LIVE (18 Aug 2026): every value this module ever
# extracted was stored exactly as printed, with no unit-scale conversion
# at all. `normalize_label` above already recognised a "(Rs.'000)"-style
# annotation — but only to STRIP it as label noise, never to capture it
# and scale the VALUE. Confirmed by downloading COMB.N0000's real
# 30.06.2026 interim statement PDF directly and reading its own balance-
# sheet page: the column header literally reads "Rs.'000 Rs.'000 % Rs.'000
# Rs.'000", and the stored `total_equity` figure (363,888,905) is exactly
# 1000x too small to be COMB's real total equity — the true value is
# LKR 363,888,905,000 (≈364 billion), the only figure in the right order
# of magnitude for Sri Lanka's largest private bank by assets. Every
# downstream fair value computed from an unscaled figure was wrong by the
# same 1000x.
#
# NOT EVERY CSE FILING IS IN THOUSANDS, THOUGH — a real, already-verified
# counter-example already lived in this project's own test fixtures
# before this fix: Swadeshi Industrial Works PLC's real FY2025/26
# statements print "Rs. Rs. Rs. Rs." as their column header (see
# BALANCE_SHEET_TEXT_SWAD/INCOME_STATEMENT_TEXT_SWAD in test_financial_
# statement_parsing.py) — genuinely FULL Rupee values, no scaling at all
# (Revenue of 4,649,049,764 is a real ~4.6bn LKR annual figure for that
# company; interpreted as thousands it would be an impossible 4.6
# TRILLION). A single "always multiply by 1000" fix would have been
# WRONG for this real, already-known case — this is why detection, not a
# blanket assumption, is required.
#
# Three real, verified thousands-declaration wordings feed
# `_UNIT_THOUSANDS_RE`: J.F. Packaging PLC's "Rs.000" (no apostrophe),
# Asian Hotels & Properties PLC's "In Rs.'000s" (apostrophe + trailing
# "s"), and Commercial Bank of Ceylon PLC's "Rs.'000" (apostrophe, no
# trailing "s") — real evidence from three independently-verified real
# filings, not one pattern generalised from a single example.
# `_UNIT_FULL_VALUE_RE` requires "Rs." to repeat at least twice
# consecutively (matching Swadeshi's real "Rs. Rs. Rs. Rs." header
# exactly) rather than matching on a single stray "Rs." anywhere on the
# page, which could appear incidentally in unrelated body text.
#
# THE APOSTROPHE ITSELF HAS TWO REAL ENCODINGS, FOUND LIVE. COMB.N0000's
# own real 2019 annual report (a different filing/toolchain vintage from
# its 2026 interim statement checked first) renders the SAME "Rs.'000"
# declaration with a Unicode RIGHT SINGLE QUOTATION MARK (U+2019, "’"),
# not the straight ASCII apostrophe (U+0027, "'") the original pattern
# only matched — pdfplumber decodes whichever glyph the PDF's own
# embedded font actually maps to that position, and this is a genuine,
# observed difference across real filings, not an OCR error. Confirmed
# by inspecting the exact codepoint on a real downloaded PDF
# (`Rs. ’000`) after this exact gap silently dropped 11 real,
# extractable statement/summary pages (including the real primary
# balance sheet on page 142) from that one filing alone — caught by a
# dedicated diagnostic run, not by re-reading the regex in the abstract.
#
# THE CURRENCY PREFIX ITSELF ISN'T ALWAYS "RS." EITHER. Nations Trust
# Bank PLC's real interim statement for the six months ended 30 June
# 2026 declares its units as "LKR '000" on its real Statement of Cash
# Flows page — never "Rs." at all. This is a genuine, verified fourth
# wording variant, not a guess: the original "rs"-only pattern refused
# every one of NTB.N0000's real primary-statement pages (0 drafts
# produced across two separate backfill runs) even though a real,
# well-formed unit declaration WAS present on the page, just spelled
# with a different currency abbreviation. Found live via a dedicated
# diagnostic download of NTB.N0000's own real filing, the same method
# used for the two gaps documented above.
#
# A FIFTH REAL WORDING, AND A GENUINELY NEW SHAPE: full-value (not
# thousands) statements that ALSO use "LKR" rather than "Rs." — found
# live (18 Aug 2026) against Panasian Power PLC's (PAP.N0000) real
# interim statement for the quarter ended 30 June 2026. Its own real
# Statement of Financial Position column header reads plain "LKR LKR LKR
# LKR" — no "'000" suffix at all, and its own printed Total Assets
# (9,828,732,284) is only plausible as a genuine full-LKR figure (read as
# thousands, it would be a nonsensical ~9.8 TRILLION LKR for a small
# hydro/solar power company). Before this fix, `_UNIT_THOUSANDS_RE`
# correctly refused to match (no "'000"/"000" suffix present) but
# `_UNIT_FULL_VALUE_RE` ALSO refused, because it only recognised a
# repeated "Rs." — this page's own genuine, real, repeated per-column
# unit declaration used a currency prefix that pattern had never seen,
# and the page was silently skipped, 0 drafts, for the exact same "found
# a marker, refused a scale" reason NTB's doubled page was skipped before
# `repair_character_doubling` — a completely independent real gap that
# happened to produce the same symptom.
_UNIT_THOUSANDS_RE = re.compile(r"(?:rs\.?|lkr)\s*['’]?000s?\b")
_UNIT_FULL_VALUE_RE = re.compile(r"(?:\b(?:rs\.|lkr)\s*){2,}")


def detect_unit_scale(page_text: str) -> Decimal | None:
    """The multiplier every value extracted from this page must be
    multiplied by to reach real LKR — `Decimal(1000)` for a confirmed
    "Rs.'000"-style declaration, `Decimal(1)` for a confirmed "Rs."
    (full-value, no scaling) declaration.

    `None` — never a guessed default — when NEITHER pattern is found
    anywhere on the page. §5's own extraction pipeline has already shown
    real filings use genuinely different units (see the module-level
    comment above); silently assuming either 1 or 1000 for an
    undetected case would produce exactly the "plausible wrong number"
    failure mode `check_accounting_identities` exists to catch for
    arithmetic errors — but a uniform 1000x scale error passes every one
    of those identity checks (both sides of `assets = equity +
    liabilities` are wrong by the same factor), so detection has to be
    the first line of defence here, not a fallback. The caller (`app.
    ingestion.financial_pdf_extractor.extract_financial_statement_
    candidates`) skips a page entirely when this returns `None`, the
    same "refuse rather than guess" rule `classify_period_type` and
    `resolve_first_available_date` already apply to their own
    can't-tell cases.

    NOT APPLICABLE TO PER-SHARE LINES. A page-wide scale is correct for
    balance-sheet/income-statement totals, but NOT for a per-share figure
    like EPS (real filings print EPS in actual Rupees even on a page
    whose other lines are in thousands — verified on J.F. Packaging
    PLC's own real statement: "Diluted EPS (Rs.) ... 1.37"). No canonical
    key in `CANONICAL_LABELS` currently maps EPS, so this doesn't yet
    create a real double-scaling risk — but it would the moment one did,
    and that key would need to be excluded from page-wide scaling rather
    than assumed to follow it."""
    lower = page_text.lower()
    if _UNIT_THOUSANDS_RE.search(lower):
        return Decimal(1000)
    if _UNIT_FULL_VALUE_RE.search(lower):
        return Decimal(1)
    return None


def _parse_value_token(token: str) -> Decimal | None:
    if token == _NIL:
        return None
    negative = token.startswith("(") and token.endswith(")")
    digits = token.strip("()").replace(",", "")
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


@dataclass(frozen=True)
class ExtractedLine:
    raw_label: str
    statement_line: str | None  # None if the label didn't match any canonical key
    values: tuple[Decimal | None, ...]  # in the order printed, left to right
    raw_text: str
    alt_values: tuple[Decimal, ...] | None = None
    """The OTHER real possibility for the FULL values tuple, computed
    whenever this line had MORE raw numeric tokens than `expected_value_
    columns` — `None` when there was no excess, or when no plausible
    alternate reading could be built from it.

    A line with excess tokens is genuinely ambiguous by shape alone: a
    real note reference (J.F. Packaging PLC's own "Revenue 5 4,504,801
    4,385,214 2,356,951 2,371,137", where "5" really is a footnote
    number, correctly dropped) and a real split-off leading digit (e.g.
    Swisstek (Ceylon) PLC's real "Total liabilities 1 0,216,971 1
    0,163,128 2,881,063 2,481,861", where TWO of the four columns are
    really 10,216,971/10,163,128, not 1 and 0,216,971/0,163,128 as
    separate tokens) produce structurally similar excess-token shapes —
    there is no way to tell them apart from this one line alone, and a
    real filing can have EITHER, or even a non-uniform MIX of split and
    unsplit columns on one line (verified: Swisstek's own line above has
    two columns split and two not).

    `alt_values` is what the full tuple would read as if EVERY adjacent
    (note-reference-shaped token, value-shaped token) pair still present
    after the DEFAULT reading's own excess-token handling were instead a
    split-off leading digit, rejoined — kept alongside the normal
    `values` (never substituted here) so a page-level pass with more
    context (`reconcile_ambiguous_values_via_identities`) can pick
    whichever one actually balances against the rest of the statement,
    rather than either guessing or always assuming the more common case
    (a genuine note reference) is the only one that exists. Only
    populated when the merge produces EXACTLY `expected_value_columns`
    values — anything else means the line's shape doesn't cleanly
    resolve either way, and no alternate is offered instead of a wrong
    one."""

    @property
    def primary_value(self) -> Decimal | None:
        """The first (left-most) numeric column. CSE statements
        conventionally list the most recent period first and Group before
        Company — verified on J.F. Packaging PLC — but this is a
        convention, not a guarantee; every column CSE actually printed is
        preserved in `raw_text` for a human reviewer to check before
        confirming."""
        return self.values[0] if self.values else None


def _join_split_leading_digit(lead: str, rest: str) -> str:
    """Reconstructs the single raw value token pdfplumber split into
    `lead` (the standalone leading digit(s)) and `rest` (the remainder,
    with its own thousands-grouping and optional parenthesised sign
    intact) — e.g. `("8", "27,386")` -> `"827,386"`, `("1", "(0,216,971)")`
    -> `"(10,216,971)"`. Only the digits get concatenated; punctuation
    (commas, parens) stays exactly where `rest` already has it, since
    `lead` is only ever the number's true leading digit(s), never a sign
    or grouping character of its own."""
    if rest.startswith("(") and rest.endswith(")"):
        return "(" + lead + rest[1:]
    return lead + rest


def _merge_all_split_pairs(
    numeric_tokens: list[str], expected_value_columns: int
) -> tuple[Decimal, ...] | None:
    """The alternate reading `ExtractedLine.alt_values` needs — see that
    field's own docstring for the real ambiguity this exists for. Greedy
    left-to-right scan: every adjacent (note-reference-shaped token,
    value-shaped token) pair is rejoined into one number, exactly like a
    single excess leading token would be, but applied uniformly across
    the WHOLE line rather than only at the front — Swisstek's own real
    "Total liabilities 1 0,216,971 1 0,163,128 2,881,063 2,481,861" has
    TWO such pairs (columns 1 and 2), not one, and a single-token
    restriction (only ever checking the very first token) would miss the
    second.

    DELIBERATELY NOT applied unconditionally — this is only ever offered
    as a CANDIDATE (`ExtractedLine.alt_values`), never used to override
    `values` here. Merging is aggressive on purpose (it would happily
    "rejoin" a genuine trailing note reference too, exactly the J.F.
    Packaging case this module has guarded against before) because the
    real safety check lives one layer up, in `reconcile_ambiguous_values_
    via_identities`: a candidate only ever gets used when it turns a
    FAILING accounting identity into a passing one without breaking any
    identity that already passed — J.F. Packaging's real revenue line
    already satisfies "revenue - cost of sales = gross profit" under the
    default reading, so its own alternate (however plausible-looking in
    isolation) never gets accepted.

    Returns `None` when the merged result doesn't come out to exactly
    `expected_value_columns` values, or when any merged token fails to
    parse — a line whose shape doesn't cleanly resolve either way offers
    no alternate, rather than a guessed one.
    """
    def _greedy_merge(tokens: list[str]) -> list[str]:
        merged: list[str] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            following = tokens[i + 1] if i + 1 < len(tokens) else None
            if following is not None and _NOTE_REF_RE.match(token) and _VALUE_RE.match(following):
                merged.append(_join_split_leading_digit(token, following))
                i += 2
            else:
                merged.append(token)
                i += 1
        return merged

    merged = _greedy_merge(numeric_tokens)
    if len(merged) != expected_value_columns and numeric_tokens and _NOTE_REF_RE.match(numeric_tokens[0]):
        # A genuine leading note reference can itself sit directly in
        # front of a split-pair's own leading digit — REAL BUG THIS
        # CLOSES, found live (28 Aug 2026) tracing Chemanex PLC's real
        # confirmed `revenue`: "Revenue 1 1 07,573 1 81,246 (41)" is note
        # reference "1" followed by TWO split pairs ("1"+"07,573" =
        # 107,573, "1"+"81,246" = 181,246) then a variance value, but the
        # greedy scan above can't tell the note reference's own "1" apart
        # from the first split pair's own leading "1" — both are lone
        # digits, indistinguishable by shape — so it wrongly consumed
        # them AS a pair ("1"+"1" -> "11"), leaving 4 merged tokens for
        # an expected 3 and returning no alternate at all. Retrying with
        # that leading token dropped first resolves it cleanly; this
        # branch only ever fires when the direct merge above already
        # failed to hit the target count, so an already-correct merge
        # (Swisstek's real two-pair line, Tea Smallholder's real single-
        # pair line, J.F. Packaging's real genuine-note-reference line —
        # all already covered by existing tests) is never touched.
        merged = _greedy_merge(numeric_tokens[1:])
    if len(merged) != expected_value_columns:
        return None
    values = tuple(_parse_value_token(t) for t in merged)
    if any(v is None for v in values):
        return None
    return values


def split_label_and_values(
    line: str, expected_value_columns: int = DEFAULT_EXPECTED_VALUE_COLUMNS
) -> ExtractedLine | None:
    """Right-to-left token scan: pull numeric-looking tokens off the end
    of the line until hitting one that isn't a value, a note reference, or
    a nil marker. Returns None if the line has no trailing numeric tokens
    at all (i.e. it's not a data line — a heading, a page footer, etc.).
    """
    tokens = _repair_split_thousands(line).split()
    i = len(tokens)
    while i > 0 and (
        _VALUE_RE.match(tokens[i - 1])
        or _NOTE_REF_RE.match(tokens[i - 1])
        or _VARIANCE_PCT_RE.match(tokens[i - 1])
        or tokens[i - 1] == _NIL
    ):
        i -= 1

    numeric_tokens = tokens[i:]
    label_tokens = tokens[:i]
    if not numeric_tokens or not label_tokens:
        return None

    # Variance/change-% columns are scanned past above (so they don't
    # corrupt the label boundary — see _VARIANCE_PCT_RE's own docstring)
    # but are never a real data value, so they're dropped here, before
    # digit-repair and before expected_value_columns' count comparison
    # counts them as one of the statement's own declared value columns.
    #
    # REAL BUG THIS CLOSES, found live (28 Aug 2026) tracing JAT Holdings
    # PLC's real confirmed net_income stored as the literal digit "2":
    # `expected_value_columns` is a PAGE-level count (`detect_expected_
    # value_columns`, from the header alone), and a header like "Rs. Rs.
    # % Rs. Rs. %" is genuinely ambiguous about whether each "%" itself
    # corresponds to a real, separately-tokenisable data value — Tea
    # Smallholder's real "%"-column prints a BARE number per row ("...
    # 731,119 13", no "%" character on the value itself), which the
    # tokeniser keeps and which genuinely needs counting; JAT's own real
    # "%"-column prints the value WITH a literal "%" suffix on every row
    # ("...177% 4 00,051,561... -1991%"), which `_VARIANCE_PCT_RE` above
    # already correctly strips as never-a-real-value. Both header shapes
    # look identical from the header alone — the header genuinely cannot
    # say which behaviour a given DATA ROW will have — so
    # `expected_value_columns` ends up "budgeting" a slot for each real
    # "%" column regardless, correct for Tea Smallholder, wrong for JAT
    # (whose real 6-token-wide header count then exactly matches this
    # line's own 6 raw tokens even though 2 of those 6 are really a
    # split-off leading digit, disabling the note-reference-drop/alt-
    # values logic below entirely — `len(numeric_tokens) > expected_
    # value_columns` never fires). Adjusting the comparison count by
    # however many `_VARIANCE_PCT_RE` tokens THIS SPECIFIC LINE actually
    # had to strip is the per-line signal the header alone can't give:
    # Tea Smallholder's real line strips zero (its own "13" was never a
    # variance-shaped token to begin with), so its own count is
    # unchanged; JAT's real line strips two, correctly un-inflating the
    # comparison back down to the real 4 monetary columns.
    stripped = sum(1 for t in numeric_tokens if _VARIANCE_PCT_RE.match(t))
    numeric_tokens = [t for t in numeric_tokens if not _VARIANCE_PCT_RE.match(t)]
    if not numeric_tokens:
        return None
    effective_expected_value_columns = max(expected_value_columns - stripped, 1)

    numeric_tokens = _repair_split_leading_digits(numeric_tokens)

    # See `ExtractedLine.alt_values`'s own docstring for the real
    # ambiguity this covers — computed from the FULL excess-token list,
    # before the leading-note-reference drop below ever removes anything,
    # so a genuine second (or third) split pair further along the line
    # (Swisstek's real case) is still visible to it.
    alt_values = (
        _merge_all_split_pairs(numeric_tokens, effective_expected_value_columns)
        if len(numeric_tokens) > effective_expected_value_columns
        else None
    )

    # Drop a leading note-reference token: one more numeric token than the
    # statement's own declared column count, AND that extra leading token
    # is shaped like a note reference (short, comma-free, optionally
    # dot-separated) — see DEFAULT_EXPECTED_VALUE_COLUMNS above for why
    # count is the signal, not the token's shape alone (a bare "5" or
    # "13.2" is indistinguishable from a real small/decimal value on
    # shape).
    if len(numeric_tokens) > effective_expected_value_columns and _NOTE_REF_RE.match(numeric_tokens[0]):
        numeric_tokens = numeric_tokens[1:]

    # A SECOND leading reference: a page number followed by a note number,
    # "Other components of equity 96 25 23,093,391 22,287,036 ..." on
    # AHPL's real FY2022 balance sheet — page 96, note 25 (note 25's own
    # page is literally headed "25 OTHER COMPONENTS OF EQUITY"), then four
    # value columns; the same "<page> <note> <values...>" shape recurs on
    # CINS and CFVF's real filings. Dropping only the first kept the note
    # number ("25") as the value — flagged implausibly small, then over-
    # corrected to a spurious ~2.5-trillion merge by `_merge_all_split_
    # pairs`. Only ever a MULTI-digit token: a lone single digit in this
    # position is a pdfplumber split-off leading digit (Serendib Hotels'
    # real "Inventories 13 3 7,890 ..." — "3" belongs to "37,890"), which
    # `_merge_all_split_pairs` rejoins and which must NOT be dropped.
    if (
        len(numeric_tokens) > effective_expected_value_columns
        and len(numeric_tokens[0]) >= 2
        and _NOTE_REF_RE.match(numeric_tokens[0])
    ):
        numeric_tokens = numeric_tokens[1:]

    values = tuple(_parse_value_token(t) for t in numeric_tokens)
    if all(v is None for v in values):
        return None  # every token was a bare "-" — not useful, and likely not a real data line

    label = " ".join(label_tokens)
    return ExtractedLine(
        raw_label=label,
        statement_line=match_canonical_label(label),
        values=values,
        raw_text=line,
        alt_values=alt_values,
    )


@dataclass(frozen=True)
class IdentityCheck:
    name: str
    passed: bool
    detail: str


def check_accounting_identities(values: dict[str, Decimal]) -> list[IdentityCheck]:
    """Independent arithmetic checks on an extracted period.

    A statement that doesn't balance means the extraction is wrong, and
    this catches classes of corruption no regex can — it was an identity
    failure (equity + liabilities != assets) that exposed the split-
    thousands bug, because the two sides were mangled by different
    amounts. Cheap, deterministic, and it fails loudly on exactly the
    error mode that is otherwise invisible: a plausible wrong number.

    Only checks identities where BOTH sides were extracted; a missing
    line item is not a failure, it's simply not checkable.
    """
    checks: list[IdentityCheck] = []

    def have(*keys: str) -> bool:
        return all(k in values for k in keys)

    # Assets = Equity + Liabilities
    if have("total_assets", "total_equity", "total_liabilities"):
        lhs = values["total_assets"]
        rhs = values["total_equity"] + values["total_liabilities"]
        ok = lhs == rhs
        checks.append(
            IdentityCheck(
                "assets = equity + liabilities",
                ok,
                f"{lhs:,} vs {rhs:,}" + ("" if ok else f" — differs by {abs(lhs - rhs):,}"),
            )
        )

    # The balance sheet's own footing line must agree with total assets.
    if have("total_assets", "total_equity_and_liabilities"):
        lhs, rhs = values["total_assets"], values["total_equity_and_liabilities"]
        ok = lhs == rhs
        checks.append(IdentityCheck("assets = equity and liabilities", ok, f"{lhs:,} vs {rhs:,}"))

    # Owners' equity + non-controlling interest = total equity. Catches a
    # corrupted read of the "attributable to owners" line — found live
    # (RHL.N0000, 4 Sep 2026: extracted as 785m against a real ~21bn,
    # while `total_equity` and NCI were both fine).
    if have("equity_attributable_to_owners", "non_controlling_interest", "total_equity"):
        lhs = values["equity_attributable_to_owners"] + values["non_controlling_interest"]
        rhs = values["total_equity"]
        ok = lhs == rhs
        checks.append(
            IdentityCheck(
                "owners equity + NCI = total equity",
                ok,
                f"{lhs:,} vs {rhs:,}" + ("" if ok else f" — differs by {abs(lhs - rhs):,}"),
            )
        )

    # Current + non-current = total, both sides of the balance sheet.
    # PLUS assets/liabilities "held for sale" (IFRS 5), WHEN a company's
    # own real filing reports them — a real, genuine third bucket, found
    # live on Lanka Walltiles PLC's (LWL.N0000) real interim statement
    # for the period ended 30 June 2026 (see `assets_held_for_sale`'s own
    # comment in CANONICAL_LABELS for the full finding), NOT folded into
    # either current or non-current on that company's own balance sheet.
    # Optional and additive only: a company with no such line simply has
    # `values.get(...)` default to zero, leaving this identity exactly as
    # it was for every filing checked before LWL's (J.F. Packaging,
    # Swadeshi, AHPL, COMB, NTB, PAP — none of which have a held-for-sale
    # line at all).
    if have("total_assets", "total_current_assets", "total_non_current_assets"):
        lhs = values["total_assets"]
        held_for_sale = values.get("assets_held_for_sale", Decimal(0))
        rhs = values["total_current_assets"] + values["total_non_current_assets"] + held_for_sale
        ok = lhs == rhs
        detail = f"{lhs:,} vs {rhs:,}"
        if held_for_sale:
            detail += f" (includes assets held for sale = {held_for_sale:,})"
        checks.append(IdentityCheck("assets = current + non-current", ok, detail))

    if have("total_liabilities", "total_current_liabilities", "total_non_current_liabilities"):
        lhs = values["total_liabilities"]
        held_for_sale = values.get("liabilities_associated_with_assets_held_for_sale", Decimal(0))
        rhs = values["total_current_liabilities"] + values["total_non_current_liabilities"] + held_for_sale
        ok = lhs == rhs
        detail = f"{lhs:,} vs {rhs:,}"
        if held_for_sale:
            detail += f" (includes liabilities associated with assets held for sale = {held_for_sale:,})"
        checks.append(IdentityCheck("liabilities = current + non-current", ok, detail))

    # Revenue - cost of sales = gross profit (cost stored negative).
    if have("revenue", "cost_of_sales", "gross_profit"):
        lhs = values["revenue"] + values["cost_of_sales"]
        rhs = values["gross_profit"]
        ok = lhs == rhs
        checks.append(IdentityCheck("revenue - cost of sales = gross profit", ok, f"{lhs:,} vs {rhs:,}"))

    # Profit before tax - tax = profit for the period (tax stored negative).
    if have("profit_before_tax", "income_tax_expense", "net_income"):
        lhs = values["profit_before_tax"] + values["income_tax_expense"]
        rhs = values["net_income"]
        ok = lhs == rhs
        checks.append(IdentityCheck("pre-tax profit - tax = net income", ok, f"{lhs:,} vs {rhs:,}"))

    # CFO + investing + financing = net change in cash — the cash-flow
    # statement's own footing line. Verified against J.F. Packaging PLC's
    # real FY2025/26 figures: 174,382 + (-244,852) + 12,302 = -58,168,
    # exactly matching the printed "Net Increase/(Decrease) in Cash".
    if have(
        "cash_flow_from_operations",
        "net_cash_from_investing_activities",
        "net_cash_from_financing_activities",
        "net_increase_in_cash",
    ):
        lhs = (
            values["cash_flow_from_operations"]
            + values["net_cash_from_investing_activities"]
            + values["net_cash_from_financing_activities"]
        )
        rhs = values["net_increase_in_cash"]
        ok = lhs == rhs
        checks.append(
            IdentityCheck("CFO + investing + financing = net change in cash", ok, f"{lhs:,} vs {rhs:,}")
        )

    return checks


#: A magnitude-plausibility floor, not an accounting identity — nothing
#: above can catch a value that's simply drastically too SMALL relative
#: to the rest of its own filing when no identity happens to cover it.
#: REAL CASE (commit 313afdc, 19 Aug 2026, deliberately left unfixed at
#: the parsing layer — see `test_aafs_real_odd_count_split_digit_is_a_
#: named_unfixed_gap`): AAF.N0000's real FY2022 filing prints "Profit
#: for the year 1 18,561,733 45,196,117" — a pdfplumber split-leading-
#: digit artifact with an ODD token count, which `_repair_split_leading_
#: digits`'s own even-count-only guard correctly declines to touch (the
#: same guard that protects J.F. Packaging's genuine "Revenue 5
#: 4,504,801 ..." note-reference line from being wrongly merged). The
#: lone "1" survives as a syntactically valid net_income, and because
#: this filing's income_tax_expense wasn't also extracted, no identity
#: above happens to cover net_income at all — the wrong value sails
#: through check_accounting_identities completely clean. A second,
#: independent real case (VLL.N0000, FY ended 2012-03-31, found live
#: running this exact check for the first time): one leg of "pre-tax
#: profit - tax = net income" reads as the literal value 30 against a
#: net_income of 59,130,635 on the SAME filing — same failure shape,
#: different company, different filing.
#:
#: This ratio — a flagged value against the LARGEST other value
#: extracted from the SAME filing — is self-scaling to the company's
#: own real size rather than a fixed LKR floor that would either miss a
#: genuinely small line on a large company or false-positive on a
#: genuinely small company. Both real corrupted values above sit at a
#: ratio of 5e-7 (VLL) and ~5e-11 (AAF) — orders of magnitude below this
#: threshold — while even a genuinely thin, real quarter's net income
#: relative to total assets (checked across every real fixture and
#: every real filing referenced anywhere in this module) never comes
#: close to this floor.
_MAGNITUDE_IMPLAUSIBILITY_RATIO = Decimal("0.000001")


#: A corrected value from `reconcile_magnitude_implausible_values` must
#: still respect the balance sheet's own containment structure: a
#: component line can never exceed the subtotal it rolls up into. The
#: small-side magnitude flag (`_MAGNITUDE_IMPLAUSIBILITY_RATIO`) rescues a
#: value that reads far TOO SMALL, but on its own it will just as happily
#: accept an `alt_values` candidate that reads far TOO LARGE. REAL BUG
#: THIS CLOSES, found live (28 Aug 2026) on AHPL/CINS/CFVF: a line like
#: "Other components of equity 96 25 23,093,391 22,287,036 ..." carries a
#: note reference ("96") AND a second spurious two-digit token ("25")
#: before the real value; `_merge_all_split_pairs` fused "25" into
#: "23,093,391" -> 2,523,093,391 (~110x the real figure and 59x the
#: filing's own total equity), an alt the small-side flag cleared without
#: complaint because nothing else on the filing was then a millionth of
#: it. Each key lists the subtotal(s) that structurally bound it, most
#: specific first; the check uses whichever the filing actually extracted.
_COMPONENT_SUBTOTAL_CEILINGS: dict[str, tuple[str, ...]] = {
    "inventories": ("total_current_assets", "total_assets"),
    "trade_receivables": ("total_current_assets", "total_assets"),
    "trade_payables": ("total_current_liabilities", "total_liabilities", "total_assets"),
    "total_interest_bearing_debt": ("total_liabilities", "total_assets"),
    "revaluation_reserves": ("total_equity", "total_equity_and_liabilities"),
    "retained_earnings": ("total_equity", "total_equity_and_liabilities"),
    # §24's balance-sheet set. Each is a component of total assets (or,
    # for the overdraft, of liabilities), so the same too-LARGE misread
    # guard applies. PP&E and investment property are non-current, so
    # they are NOT bounded by total_current_assets; cash is current, so
    # it is.
    "cash_and_cash_equivalents": ("total_current_assets", "total_assets"),
    "bank_overdraft": ("total_current_liabilities", "total_liabilities", "total_assets"),
    "property_plant_and_equipment": ("total_non_current_assets", "total_assets"),
    "intangible_assets": ("total_non_current_assets", "total_assets"),
    "investment_property": ("total_non_current_assets", "total_assets"),
}
#: A little slack for real group-vs-company column mismatches and ordinary
#: publication rounding — every real over-correction found so far breaches
#: its ceiling by 6x-110x, orders of magnitude past this.
_COMPONENT_CEILING_TOLERANCE = Decimal("1.10")


def _magnitude_implausible_keys(values: dict[str, Decimal]) -> set[str]:
    """The set of keys `check_magnitude_plausibility` would flag — pulled
    out so `reconcile_magnitude_implausible_values` below can ask the
    identical question (both before AND after a candidate substitution)
    without parsing that function's own human-readable `IdentityCheck`
    messages back apart. See `check_magnitude_plausibility`'s own
    docstring for what this actually measures and why."""
    if len(values) < 2:
        return set()
    largest_key = max(values, key=lambda k: abs(values[k]))
    largest = abs(values[largest_key])
    if largest == 0:
        return set()
    flagged: set[str] = set()
    for key, value in values.items():
        if key == largest_key or value == 0:
            continue
        if abs(value) / largest < _MAGNITUDE_IMPLAUSIBILITY_RATIO:
            flagged.add(key)
    return flagged


def check_magnitude_plausibility(values: dict[str, Decimal]) -> list[IdentityCheck]:
    """A line item whose magnitude is a millionth (or less) of the
    largest OTHER value extracted from the same filing is almost
    certainly a corrupted read — a split-off leading digit, a dropped
    column, a stray footnote number captured as the value — not a real
    accounting relationship failing (`check_accounting_identities`
    already covers that). Exists specifically for the class of wrong
    value NEITHER an identity check nor `reconcile_ambiguous_values_via_
    identities` can catch: no computable identity covers the line (a
    sibling value this filing didn't also extract), and no `alt_values`
    candidate exists to reconcile against either (this isn't an
    excess-token-shaped ambiguity — see `ExtractedLine.alt_values`'s own
    docstring for that, separate, case) — see this function's own
    `_MAGNITUDE_IMPLAUSIBILITY_RATIO` comment for the two real, live
    cases this was built from.

    Returned as the SAME `IdentityCheck` shape `check_accounting_
    identities` returns, deliberately — every caller already treats a
    non-passing entry from that function as "do not confirm without
    checking the source PDF"; a plausibility failure earns the identical
    treatment through `check_extraction_quality` below rather than a
    parallel, easily-forgotten second code path.

    Needs at least two extracted values to mean anything — a single
    value has nothing to be implausible relative to — and returns
    nothing when every extracted value is exactly zero (nothing to scale
    against either).
    """
    # A genuine EXACT zero is never itself flagged — see `_magnitude_
    # implausible_keys`'s shared logic. REAL BUG THIS CLOSES, found live
    # (28 Aug 2026) tracing Pan Asia Power PLC's real confirmed `total_
    # non_current_liabilities`, printed as a literal "0" on 16
    # independent real filings running back-to-back years ("Total Non
    # current liabilities 0 922,963" — the company simply repaid all its
    # long-term debt that year, a completely ordinary accounting
    # outcome): re-verified as the SAME "0" every time, permanently un-
    # confirmable, because 0 divided by any positive `largest` is always
    # 0 and 0 is always below the ratio floor — this check could never
    # accept a genuine zero subtotal no matter how many times it was re-
    # extracted. A corrupted read (a split-off leading digit, a stray
    # footnote number captured as the value) is never itself exactly
    # zero — those artifacts are always a small but non-zero digit run —
    # so exempting a literal 0 loses no real detection power.
    if len(values) < 2:
        return []
    largest_key = max(values, key=lambda k: abs(values[k]))
    largest = abs(values[largest_key])
    checks: list[IdentityCheck] = []
    for key in _magnitude_implausible_keys(values):
        value = values[key]
        ratio = abs(value) / largest
        checks.append(
            IdentityCheck(
                f"{key} implausibly small vs {largest_key}",
                False,
                f"{key} = {value:,} is only {ratio:.2e}x this filing's own largest extracted "
                f"value ({largest_key} = {largest:,}) — almost certainly a corrupted read, not "
                "a genuine figure (see check_magnitude_plausibility's own docstring)",
            )
        )
    return checks


def reconcile_magnitude_implausible_values(
    values: dict[str, Decimal], alt_values: dict[str, Decimal]
) -> dict[str, Decimal]:
    """A complementary pass to `reconcile_ambiguous_values_via_identities`
    for the specific gap that function structurally cannot cover: a
    component line with NO accounting identity mentioning it at all
    (`inventories`, `trade_receivables` — components of a subtotal this
    module doesn't itself check, unlike `total_current_assets` or
    `total_assets`) has nothing for identity-based reconciliation to test
    a correction against, so its own `alt_values` candidate sits unused
    forever even when the DEFAULT reading is flagged outright as
    implausible by `check_magnitude_plausibility`.

    REAL CASE THIS CLOSES, found live (28 Aug 2026) tracing Serendib
    Hotels PLC's real confirmed `inventories`, stored as the literal
    digit 3: its real balance sheet line "Inventories 13 3 7,890 33,761
    8 ,306 7,597" already computes the CORRECT `alt_values` reading
    (37,890 — the note reference "13" dropped, "3"+"7,890" correctly
    rejoined) via the exact same split-pair machinery that already fixes
    every OTHER real case in this module — but `inventories` has no
    sibling identity ("total_current_assets = inventories + trade_
    receivables + ..." isn't one `check_accounting_identities`
    implements), so `reconcile_ambiguous_values_via_identities` never
    even considers it: nothing to test the correction against, forever.

    Deliberately a SEPARATE, narrower acceptance rule from identity-based
    reconciliation, not a relaxation of it: a substitution is accepted
    ONLY when (a) the key was ALREADY flagged implausible under the
    default reading, (b) an alt candidate exists for it, (c) the alt
    reading clears ITS OWN flag, (d) the substitution introduces no NEW
    implausibility flag on any other key (the corrected value becoming
    large enough to shrink another key's own ratio below the floor), and
    (e) the alt does not breach the subtotal this line structurally rolls
    into (`_COMPONENT_SUBTOTAL_CEILINGS` — the guard against a too-LARGE
    misread, symmetric with the too-small flag that opened the door).
    Each flagged key is evaluated independently against the ORIGINAL
    flagged set — never chained off a previous substitution in the same
    pass — so this stays a single, deterministic, order-independent pass,
    the same discipline `reconcile_ambiguous_values_via_identities`
    already holds itself to.
    """
    originally_flagged = _magnitude_implausible_keys(values)
    corrections: dict[str, Decimal] = {}
    for key in originally_flagged:
        if key not in alt_values:
            continue
        candidate = dict(values)
        candidate[key] = alt_values[key]
        new_flags = _magnitude_implausible_keys(candidate)
        if key in new_flags:
            continue  # the alt itself is still implausible — not a fix
        if new_flags - originally_flagged:
            continue  # would newly implicate a key that was fine before
        ceiling = next(
            (
                abs(values[c])
                for c in _COMPONENT_SUBTOTAL_CEILINGS.get(key, ())
                if c in values and values[c] != 0
            ),
            None,
        )
        if ceiling is not None and abs(alt_values[key]) > ceiling * _COMPONENT_CEILING_TOLERANCE:
            continue  # the alt would exceed the subtotal this line rolls into —
            # a too-large misread (a fused spurious token), not a fix
        corrections[key] = alt_values[key]
    return corrections


def check_extraction_quality(values: dict[str, Decimal]) -> list[IdentityCheck]:
    """Every automated check this module runs against one filing's
    extracted values before any of them is trusted — `check_accounting_
    identities` (exact arithmetic relationships) PLUS `check_magnitude_
    plausibility` (the self-scaling floor that catches a corrupted value
    no identity happens to cover). Every real caller — `app.ingestion.
    financial_pdf_extractor.ingest_financial_statement`, that module's
    own `refresh_stale_fundamentals`, and `app.cli`'s `refresh-stale-
    fundamentals` command — calls this instead of either check alone, so
    a filing gets the same "do not confirm without checking the source
    PDF" treatment regardless of which of the two checks is what actually
    caught it. Kept as two separate, single-purpose functions rather
    than merged into one, matching this module's own established
    discipline (see e.g. `check_accounting_identities` vs `_identity_
    diffs` vs `reconcile_ambiguous_values_via_identities` — one real
    check per function, composed by their callers) — this is that
    composition.
    """
    return check_accounting_identities(values) + check_magnitude_plausibility(values)


#: Real filings routinely show a Rs. 1-or-2 discrepancy on an otherwise-
#: correct identity — ordinary publication rounding, not an extraction
#: bug (seen throughout this project's own real fixtures and live runs).
#: `reconcile_ambiguous_values_via_identities` treats a diff at or below
#: this as "passing" rather than requiring bit-for-bit equality the way
#: `check_accounting_identities`'s own `IdentityCheck.passed` deliberately
#: does (that field exists to surface even a tiny real discrepancy to a
#: human reviewer, which is the opposite job) — every real leading-digit-
#: drop error found so far is wrong by tens of millions at least, orders
#: of magnitude past this, so the two error classes never get confused.
_IDENTITY_ROUNDING_TOLERANCE = Decimal(1000)


def _identity_diffs(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """The SAME relationships `check_accounting_identities` checks,
    returned as `{name: abs(lhs - rhs)}` instead of a pass/fail — kept as
    a genuinely separate computation (not derived from that function's
    own output) because `reconcile_ambiguous_values_via_identities` needs
    to compare MAGNITUDES with a tolerance (see `_IDENTITY_ROUNDING_
    TOLERANCE`), not the exact `lhs == rhs` that function's own result is
    deliberately built on. Keep both in sync by hand if a new identity is
    ever added to either."""
    def have(*keys: str) -> bool:
        return all(k in values for k in keys)

    diffs: dict[str, Decimal] = {}
    if have("total_assets", "total_equity", "total_liabilities"):
        diffs["assets = equity + liabilities"] = abs(
            values["total_assets"] - (values["total_equity"] + values["total_liabilities"])
        )
    if have("total_assets", "total_equity_and_liabilities"):
        diffs["assets = equity and liabilities"] = abs(
            values["total_assets"] - values["total_equity_and_liabilities"]
        )
    if have("equity_attributable_to_owners", "non_controlling_interest", "total_equity"):
        diffs["owners equity + NCI = total equity"] = abs(
            (values["equity_attributable_to_owners"] + values["non_controlling_interest"])
            - values["total_equity"]
        )
    if have("total_assets", "total_current_assets", "total_non_current_assets"):
        held = values.get("assets_held_for_sale", Decimal(0))
        diffs["assets = current + non-current"] = abs(
            values["total_assets"]
            - (values["total_current_assets"] + values["total_non_current_assets"] + held)
        )
    if have("total_liabilities", "total_current_liabilities", "total_non_current_liabilities"):
        held = values.get("liabilities_associated_with_assets_held_for_sale", Decimal(0))
        diffs["liabilities = current + non-current"] = abs(
            values["total_liabilities"]
            - (values["total_current_liabilities"] + values["total_non_current_liabilities"] + held)
        )
    if have("revenue", "cost_of_sales", "gross_profit"):
        diffs["revenue - cost of sales = gross profit"] = abs(
            (values["revenue"] + values["cost_of_sales"]) - values["gross_profit"]
        )
    if have("profit_before_tax", "income_tax_expense", "net_income"):
        diffs["pre-tax profit - tax = net income"] = abs(
            (values["profit_before_tax"] + values["income_tax_expense"]) - values["net_income"]
        )
    if have(
        "cash_flow_from_operations", "net_cash_from_investing_activities",
        "net_cash_from_financing_activities", "net_increase_in_cash",
    ):
        diffs["CFO + investing + financing = net change in cash"] = abs(
            (
                values["cash_flow_from_operations"]
                + values["net_cash_from_investing_activities"]
                + values["net_cash_from_financing_activities"]
            )
            - values["net_increase_in_cash"]
        )
    return diffs


#: A defensive cap, not a real-world limit ever actually approached —
#: every real filing found so far has 1-2 ambiguous keys on one
#: statement, never more than a handful. Guards `reconcile_ambiguous_
#: values_via_identities`'s subset search (2^n) against a pathological
#: input rather than any case seen in practice.
_MAX_AMBIGUOUS_KEYS_TO_RECONCILE = 12


def reconcile_ambiguous_values_via_identities(
    values: dict[str, Decimal], alt_values: dict[str, Decimal]
) -> dict[str, Decimal]:
    """For every canonical key with a genuinely ambiguous alternate
    reading (`alt_values` — see `ExtractedLine.alt_values`'s own
    docstring), decides which of the two the real figure actually is by
    testing every combination of substitutions against `_identity_diffs`,
    rather than guessing, always preferring one interpretation, or trying
    keys one at a time. Returns `{statement_line: corrected_value}` —
    only for keys this function actually changed its mind about; every
    key not in the result should keep its original (default) reading.

    A REAL CASE A ONE-KEY-AT-A-TIME VERSION GETS WRONG, FOUND LIVE (20
    Aug 2026): eChannelling PLC's real "Total Current Liabilities" AND
    "Total Liabilities" lines are BOTH missing the same leading digit
    (219,185,791 misread as 19,185,791; 238,125,232 misread as 38,125,232)
    — and because BOTH the subtotal and one of its own components are
    wrong by the identical amount, "liabilities = current + non-current"
    PASSES on the wrong values (the error cancels in that one specific
    sum) while "assets = equity + liabilities" fails. Correcting EITHER
    key alone makes the current-vs-non-current identity go from passing
    to failing (only one side of it would be fixed) — a one-at-a-time
    rule that never breaks an already-passing identity would reject both
    individually and end up applying neither. Trying every SUBSET of the
    ambiguous keys and scoring each by "how many identities that were
    genuinely failing now pass, given every substitution in this subset
    applied together" finds that BOTH corrected together fixes "assets =
    equity + liabilities" while leaving "liabilities = current + non-
    current" exactly where it started (correct + correct still sums
    right) — the only subset that breaks nothing and fixes something.

    THE HARD CONSTRAINT, same spirit as before: a subset is only ever
    considered if it does not turn any identity that was genuinely
    passing in the ORIGINAL (all-default) values into a failing one.
    This is what protects J.F. Packaging PLC's real "Revenue 5 4,504,801
    ..." line (see `_merge_all_split_pairs`'s own docstring) — its
    default reading already satisfies "revenue - cost of sales = gross
    profit", so any subset including its alternate is rejected outright,
    however plausible-looking the alternate is on its own.

    "Passing"/"failing" here means `_identity_diffs`' magnitude compared
    against `_IDENTITY_ROUNDING_TOLERANCE`, not bit-for-bit equality —
    see that constant's own docstring for why a real filing's own tiny
    rounding noise must not be confused with a genuine (and far larger)
    extraction error.
    """
    if not alt_values or len(alt_values) > _MAX_AMBIGUOUS_KEYS_TO_RECONCILE:
        return {}

    keys = [k for k in alt_values if k in values]
    if not keys:
        return {}

    baseline_diffs = _identity_diffs(values)
    baseline_failing = {n for n, d in baseline_diffs.items() if d > _IDENTITY_ROUNDING_TOLERANCE}
    baseline_passing = set(baseline_diffs) - baseline_failing
    if not baseline_failing:
        return {}  # nothing is actually wrong yet — no substitution can "fix" a clean statement

    best_subset: frozenset[str] = frozenset()
    best_fixed_count = 0
    for mask in range(1, 1 << len(keys)):
        subset = frozenset(keys[i] for i in range(len(keys)) if mask & (1 << i))
        candidate = dict(values)
        for key in subset:
            candidate[key] = alt_values[key]
        candidate_diffs = _identity_diffs(candidate)

        breaks_something_passing = any(
            candidate_diffs.get(name, Decimal(0)) > _IDENTITY_ROUNDING_TOLERANCE
            for name in baseline_passing
        )
        if breaks_something_passing:
            continue

        fixed_count = sum(
            1
            for name in baseline_failing
            if candidate_diffs.get(name, _IDENTITY_ROUNDING_TOLERANCE + 1) <= _IDENTITY_ROUNDING_TOLERANCE
        )
        if fixed_count > best_fixed_count or (
            fixed_count == best_fixed_count and len(subset) < len(best_subset)
        ):
            best_fixed_count = fixed_count
            best_subset = subset

    if best_fixed_count == 0:
        return {}
    return {key: alt_values[key] for key in best_subset}


#: Canonical keys that get derived by summing OTHER canonical keys, and
#: exactly which ones. Kept as data (not scattered ad-hoc across callers)
#: so `derive_additional_line_items` stays a single, inspectable place —
#: adding a second derived concept later is a new dict entry, not a new
#: function.
DERIVED_SUMS: dict[str, tuple[str, ...]] = {
    "depreciation_and_amortisation": ("depreciation_expense", "amortisation_expense"),
}

#: Canonical keys derived as (minuend - subtrahend) of two OTHER
#: canonical keys — the same "data, not a hardcoded branch" discipline
#: as DERIVED_SUMS, for concepts that are a DIFFERENCE rather than a
#: total. `change_in_net_working_capital`: the operating-activities
#: section of the cash-flow statement runs
#:   Operating Profit before Working Capital Changes
#:     + (net cash effect of every working-capital line item)
#:     = Cash generated from Operations
#: — verified on BOTH J.F. Packaging PLC and Swadeshi Industrial Works
#: PLC's real filings, where the two bookend subtotals are consistently
#: worded even though the individual component lines between them are
#: not (5 differently-named lines on one filing, 4 on the other — see
#: CANONICAL_LABELS' own comment on these two keys). Rearranging:
#:   net cash effect = cash_generated_from_operations
#:                        - operating_profit_before_working_capital_changes
#: which is POSITIVE when working capital released cash and NEGATIVE
#: when it absorbed cash. §18's DCF convention is the opposite sign — an
#: INCREASE in net working capital (cash absorbed) is a POSITIVE
#: `change_in_net_working_capital` that REDUCES FCFF when subtracted —
#: so the derived value here is the negation, expressed directly as
#: (operating_profit_before_working_capital_changes - cash_generated_
#: from_operations) rather than computing the cash effect and flipping
#: its sign in a second step. Verified against J.F. Packaging's real
#: figures: 681,378 - 493,497 = 187,881, matching the independently
#: hand-summed total of all 5 real working-capital component lines on
#: that filing exactly.
DERIVED_DIFFERENCES: dict[str, tuple[str, str]] = {
    "change_in_net_working_capital": (
        "operating_profit_before_working_capital_changes",
        "cash_generated_from_operations",
    ),
    # The balance sheet's defining identity: shareholders' equity is
    # total assets minus total liabilities. Derived only when a filing
    # prints the two totals but not the equity line itself (common on
    # bank / finance-company interims, which lead with assets and
    # liabilities) — never when `total_equity` was read directly. This is
    # the single most reliable identity in the whole statement, and it
    # recovers book value per share for names whose recent filings carry
    # a balance sheet but stopped naming the equity subtotal.
    "total_equity": ("total_assets", "total_liabilities"),
    # Owners' equity = total equity - non-controlling interest. Derived
    # only when a filing prints the group total and the NCI line but not
    # the "attributable to owners" subtotal itself. This is the base a
    # per-share book value must use — see `equity_attributable_to_owners`
    # in CANONICAL_LABELS.
    "equity_attributable_to_owners": ("total_equity", "non_controlling_interest"),
}


def derive_additional_line_items(values: dict[str, Decimal]) -> dict[str, Decimal]:
    """Canonical concepts that only exist as an arithmetic combination of
    OTHER extracted lines on at least one real filing shape — currently:

      - `depreciation_and_amortisation`, when a company reports
        Depreciation and Amortization as two separate cash-flow-statement
        lines (verified: Swadeshi Industrial Works PLC) rather than one
        combined line (verified: J.F. Packaging PLC).
      - `change_in_net_working_capital`, computed from the two bookend
        subtotals of the working-capital-changes section rather than
        summing its unpredictable, company-varying set of component
        lines — see `DERIVED_DIFFERENCES`'s own comment for the identity
        this rests on.
      - `net_working_capital` (the STOCK §18's `working_capital_pct_
        revenue` needs, a different figure from the CHANGE above), summed
        from `NET_WORKING_CAPITAL_ASSET_COMPONENTS` minus
        `NET_WORKING_CAPITAL_LIABILITY_COMPONENTS` — WHICHEVER of each
        group's keys are actually present for a given company, since the
        two real filings this was verified against have genuinely
        different component breakdowns (see those constants' own
        comment).

    All three follow the same core rules: a key is only derived when its
    required inputs are present, and NEVER when the key itself was
    already directly extracted (a company that prints a figure directly
    is trusted on that figure, never silently overwritten by a derived
    one computed from elsewhere on the same page). A partial derivation
    is never produced either — a missing input skips that key entirely
    rather than guessing, which would look exactly as precise as a real
    figure while being wrong. `net_working_capital` applies this same
    "no partial derivation" rule at the GROUP level: at least one asset
    component AND at least one liability component must be present, or
    nothing is derived — a one-sided figure (all assets, no liabilities
    counted) would look like a real net position while actually being
    gross assets alone.
    """
    derived: dict[str, Decimal] = {}
    for target_key, component_keys in DERIVED_SUMS.items():
        if target_key in values:
            continue
        if all(k in values for k in component_keys):
            derived[target_key] = sum((values[k] for k in component_keys), Decimal(0))

    for target_key, (minuend_key, subtrahend_key) in DERIVED_DIFFERENCES.items():
        if target_key in values:
            continue
        if minuend_key in values and subtrahend_key in values:
            derived[target_key] = values[minuend_key] - values[subtrahend_key]

    if "net_working_capital" not in values:
        asset_keys_present = [k for k in NET_WORKING_CAPITAL_ASSET_COMPONENTS if k in values]
        liability_keys_present = [k for k in NET_WORKING_CAPITAL_LIABILITY_COMPONENTS if k in values]
        if asset_keys_present and liability_keys_present:
            assets_total = sum((values[k] for k in asset_keys_present), Decimal(0))
            liabilities_total = sum((values[k] for k in liability_keys_present), Decimal(0))
            derived["net_working_capital"] = assets_total - liabilities_total

    return derived


def extract_candidate_lines(
    page_text: str, expected_value_columns: int = DEFAULT_EXPECTED_VALUE_COLUMNS
) -> list[ExtractedLine]:
    """All parseable lines from one page's text, not just canonical
    matches — callers that want only line items usable as Fundamental
    drafts should filter on `.statement_line is not None`, but keeping
    everything here makes this function's output independently
    inspectable/debuggable."""
    results = []
    for raw_line in page_text.splitlines():
        parsed = split_label_and_values(raw_line, expected_value_columns)
        if parsed is not None:
            results.append(parsed)
    return results
