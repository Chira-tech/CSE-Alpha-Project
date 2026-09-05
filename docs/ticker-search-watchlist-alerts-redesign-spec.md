# Ticker Search, Watchlist & Alerts — Redesign Spec

**For:** Claude Code, working directly in the CSE platform repo
**Companion to:** `company-page-and-homepage-redesign.md`, `portfolio-page-redesign-spec.md`, `scoreboard-queue-redesign-spec.md`, `mobile-responsive-implementation-spec.md` — same dark "quiet institutional terminal" tokens, same component-state model, same badge components. Nothing here introduces a new visual language; it fills three real gaps in the existing one.

The three gaps, in the user's own words: *"when I type a ticker it doesn't give a dropdown list," "I'd like to maintain the watchlist here and get more information on the shares I add," "quick actions or a push notification that comes when market looks good to enter — or not recommending."*

---

## 0. What "good" looks like here, before touching any component

Before designing the alert system in particular, it's worth being precise about what actually helps someone hold to a decision — because a badly-designed alert makes this product *worse* than having none, by re-introducing the exact impulsiveness the Journal's §45 ("what would prove me wrong") already exists to fight.

**What professional and behavioral-finance sources converge on, before someone acts on a trade idea:**

- A one-line **thesis** — why this, why now — not a ticker and a number.
- The **valuation range**, not a single false-precision price (this app already does this — the ladder/football-field work is the right instinct).
- A **named risk and a named thesis-breaker** — the specific, checkable condition that would prove the idea wrong. This app already collects this in the Journal (§45) and correctly calls it "the highest-value field on this form." Alerts should feed this discipline, not bypass it.
- Awareness of **your own biases in the moment**: loss aversion (holding losers too long, hoping), FOMO/herd behavior (buying because a price is moving, not because it's cheap), overconfidence (skipping the checklist because "I already know this one"), anchoring (comparing to the price you first saw it at, not to fair value today), and confirmation bias (an alert that only ever tells you what you want to hear). [Source: William & Mary — 5 Behavioral Biases That Can Impact Your Investing Decisions](https://online.mason.wm.edu/blog/behavioral-biases-that-can-impact-investing-decisions)
- **Friction before the impulsive action, not before the rational one.** Behavioral-design research on trading apps recommends deliberate micro-friction (a confirmation step, a cooling-off default) specifically around high-emotion, high-speed actions — while keeping routine, low-stakes actions (checking a watchlist, opening a company page) frictionless. [Source: Open Web Solutions — Behavioral Design in Trading Apps: 9 UX Patterns for Better Decisions](https://openwebsolutions.in/blog/behavioral-design-trading-apps-ux-patterns/)

This spec applies those four points concretely: the search/watchlist work below is about **removing friction from finding and monitoring** a stock; the alerts work is about **adding just enough friction, and just enough context, before you act** on what the engine surfaces. Both matter, and they pull in opposite directions on purpose.

This is also directly aligned with law 6 already printed at the bottom of the app's own sidebar: *"There is no BUY button in this product, by design."* Nothing added here introduces one. Alerts describe conditions; they never issue instructions.

---

## 1. Ticker search / autocomplete

### 1.1 What's broken today

Typing a ticker — in the Journal's `TICKER` field, and anywhere else a ticker is entered — is a bare text input with no suggestions. The `⌘K` "Search companies…" affordance already exists in the sidebar (per the homepage/company-page spec), which means the *data* and *routing* for company search almost certainly already exist somewhere in the codebase — this is very likely a matter of **exposing the existing company search as a proper combobox on every ticker input**, not building search from scratch. Check for an existing `⌘K` implementation before writing a new one.

### 1.2 Where this applies

Every place a user types a ticker becomes the same component (one component, reused, per the app's own "reads as one system" principle already stated in the scoreboard spec):

- Journal → Record a decision → `TICKER` field
- Sidebar `⌘K` global search
- Watchlist → "Add ticker" (new, see §2)
- Portfolio → "Add holding"
- Any future alert-creation form (see §3)

### 1.3 Behavior spec

- **Trigger:** starts suggesting after 1 character (tickers are short — CSE codes like `HNB.N0000` — waiting for 2-3 characters as generic-search guidance suggests is too late here). Debounce 120-150ms.
- **Match surface:** ticker code, company name, and sector/industry — a user typing "bank" should see banking names, not just literal ticker matches. Match against the same confirmed universe table the rest of the app reads from (per `cse-universe-integrity-rollout.md` — one security master, not an ad hoc list).
- **Result cap:** 8 results on screen before scrolling (mobile-safe, matches general autocomplete guidance of ~8-10 max to avoid overload). [Source: Coveo — 6 UX Design Best Practices for Autocomplete Suggestions](https://www.coveo.com/blog/autocomplete-suggestions-ux-best-practices/)
- **Ranking, most relevant first:**
  1. Exact ticker prefix match
  2. Your watchlist / portfolio holdings (boost — you search your own names most often)
  3. Company name prefix match
  4. Fuzzy/substring match on ticker, name, or sector
- **Row content** — this is where this app should exceed a generic search box, because the data already exists elsewhere in the product:
  ```
  ┌───────────────────────────────────────────────────────────┐
  │ HNB   Hatton National Bank PLC          Banking            │
  │       LKR 314.00  ▲0.6%          Buy · score 84            │
  ├───────────────────────────────────────────────────────────┤
  │ HNB.X Hatton National Bank PLC (X)      Banking            │
  │       LKR 298.00  ▲0.4%          Buy · score 84            │
  └───────────────────────────────────────────────────────────┘
  ```
  Ticker (bold, matched substring highlighted) + full company name + sector chip on the identity line; live price, day change, verdict badge (reuse the standardized badge component from the Portfolio/Opportunities specs) and score on the second line. This directly resolves the "more than one listed line" ambiguity flagged in `company-page-and-homepage-redesign.md` §1.3 — voting/non-voting lines for the same company are visually distinguished right in the dropdown instead of only being discoverable after navigating in.
- **Keyboard:** `↑`/`↓` moves the active row, `Enter` selects it, `Esc` closes without selecting, `Tab` also selects (don't punish someone for tabbing forward). Standard combobox (`role="combobox"` + `aria-activedescendant`) — not a custom div soup — so screen readers get it for free.
- **Empty/no-match state:** never a blank dropdown. *"No match for 'xyz' in the confirmed universe — [37 names pending confirmation →]"* if applicable, linking to the Confirm queue, consistent with the app's "never silently absent" data principle (§18 of the project spec).
- **Loading state:** skeleton rows at final row height, never a spinner replacing the input.
- **Mobile:** same component, full-width, results list capped to viewport height with internal scroll, dismiss via a visible close (X), not just tap-outside (per mobile autocomplete guidance).

### 1.4 Journal-specific fix

The Journal's ticker field today is free text with no validation — meaning a decision can be recorded against a ticker that isn't in the confirmed universe at all (typos become permanent journal entries, and per the Journal's own framing, "never edited afterwards"). Once this becomes the shared combobox, **require selection from the list to enable "Record decision"** — free text that matches nothing should visibly disable the submit button with a one-line reason, not silently accept garbage into a frozen record.

---

## 2. Watchlist — from a Journal action tag to a first-class screen

### 2.1 What's actually happening today

"Watchlist" currently exists only as one of the `ACTION` dropdown values on the Journal's decision form (`watchlist` / presumably `buy` / `sell` / etc.). That means the *only* way to see your watchlist right now is to scroll the Journal's decision history looking for rows tagged `watchlist` — there is no place that answers "what am I currently watching, and how is it doing today." That's the gap the user is naming.

### 2.2 The fix: Watchlist becomes its own screen, sourced from the Journal but not buried in it

Keep the Journal's `watchlist` action exactly as-is as the *event log* (it's already doing its job: freezing the reasoning and the numbers at the moment you added something). Add a new **Watchlist** view — either its own sidebar entry between Portfolio and Macro, or a tab on Today — that is a **live-refreshed roster**, not a historical log: one row per currently-watched ticker, always showing today's numbers, not the numbers frozen at add-time.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Watchlist (6)                                    [+ Add ticker]   ⌘K     │
│ What I'm watching, and how close it is to the price I said I'd act at.   │
├──────────────────────────────────────────────────────────────────────────┤
│ NEAR BUY ZONE (1)                                                         │
│ → NTB.N0000  LKR 314.00  →  Buy below 312.79  ·  1.02% away      [open]  │
├──────────────────────────────────────────────────────────────────────────┤
│ Ticker      Price    Verdict   Score  Fair Val  Buy below  Δ to buy  Added│
│ NTB.N0000   314.00   Fair      74     347.55    312.79     +0.4%   18d   │
│  ⓘ Conviction 3/5 · "watching for a pullback toward buy-below"           │
│ ─────────────────────────────────────────────────────────────────────── │
│ CBNK.N0000   7.40    Buy       88      10.04       —        —       3d   │
│ ─────────────────────────────────────────────────────────────────────── │
│ ...                                              [Sort: nearest buy ▾]   │
└──────────────────────────────────────────────────────────────────────────┘
```

**Per-row information** (answers the user's "get more information on the shares I add" directly):

- Live price + day change (▲/▼, never color alone)
- Verdict badge (same standardized component: Strong Buy / Buy / Accumulate / Hold / Reduce / Sell / Avoid)
- Composite score (reuse the score-bar mini-component from the Opportunities table)
- Fair value + buy-below / trim-above from this system's own price ladder
- **Distance to buy zone**, signed and prominent — this is the single number a watcher actually wants ("how close is it") and it doesn't exist anywhere today
- Macro regime tag if the row's sector is materially macro-sensitive (reuse the macro→valuation translation pattern from the homepage spec)
- Data freshness — if the underlying price or financials are stale, show the same amber "provisional" treatment used everywhere else, never silently
- Your own conviction (1-5) and reasoning, collapsed into an `ⓘ` popover exactly like the Portfolio table's signal popover — never inline text that breaks row height (same bug already diagnosed and fixed in `portfolio-page-redesign-spec.md` §1, don't reintroduce it here)
- Days since added — cheap, and answers "have I been watching this too long without acting"

**"Near buy zone" strip at the top** — the same "attention-first ordering" principle already used on Portfolio (`NEEDS ATTENTION`) and the homepage (`3 DECISIONS TODAY`): anything within a small configurable band of its buy-below price (e.g. ≤3%) surfaces here first, because that's the one row that might need a decision today. Everything else stays in the table.

### 2.3 Quick actions (per row, and bulk)

One consistent quick-actions affordance, reused across Watchlist, Portfolio, and Opportunities — a kebab menu or hover-reveal icon row, not four different patterns on four different screens:

| Action | What it does |
|---|---|
| **Open company** | Full company page (existing) |
| **Record decision** | Opens the Journal form, ticker pre-filled — closes the loop back to the existing decision-capture flow rather than duplicating it |
| **Set alert** | Opens the alert-creation panel (§3.4), pre-filled with sensible defaults from this row's own ladder |
| **Adjust conviction / edit reasoning** | Inline edit of the *live* watchlist entry's notes — distinct from the Journal's frozen historical record; this is "how I feel about it now," the Journal is "what I decided and why, at that moment" |
| **Remove from watchlist** | Removes from the live roster only; the historical Journal entries are never deleted (append-only stays append-only) |

Bulk: multi-select rows → bulk "set alert" (same threshold logic applied to several names at once) and bulk remove.

### 2.4 Adding a ticker

"+ Add ticker" opens the same combobox from §1, and adding a ticker **is itself a Journal `watchlist` decision** under the hood (same form, same required reasoning + "what would prove me wrong" fields) — so the existing discipline isn't bypassed by a faster add path. The Watchlist screen is the *view*; the Journal remains the *record*.

### 2.5 Empty state

*"Nothing watched yet — search a company above, or open Opportunities to find one worth watching →"* — links outward rather than just sitting blank.

---

## 3. Alerts and "push notification" system

### 3.1 The hard constraint, stated up front

Per the product's own design law: **no alert issues an instruction.** An alert describes a condition the deterministic engine already computed on schedule (per `scoreboard-queue-redesign-spec.md` §2 — precomputed, never live-triggered on request) and links to the full reasoning. The user decides; the system never says "buy now." This is not a style preference, it's the same principle that makes every score and verdict in this app explainable rather than a black box (project spec §19, §21).

### 3.2 What triggers an alert

All of these are conditions the engines already compute nightly — this is a notification layer on top of existing outputs, not a new analytical engine:

| Trigger | Example | Why it matters |
|---|---|---|
| **Entered buy zone** | Price crosses below `buy_below` for a watched/held ticker | The condition the whole Journal/watchlist flow exists to catch |
| **Left buy zone / entered expensive-or-exit zone** | Price rallies past `trim_above`, or verdict drops to Reduce/Sell/Avoid | The "not recommending" case the user explicitly asked for — a warning, not just a green signal |
| **Verdict change** | Buy → Accumulate, or Hold → Exit | Matches the homepage's existing "3 decisions today" logic — this is that same event, pushed instead of only pulled |
| **Thesis-breaker fired** | The specific, checkable condition recorded in the Journal's §45 field is now true (e.g. "NIM below 3.4% for two consecutive quarters" gets confirmed in a new filing) | This is the highest-value alert in the whole system — it's the one the user already told the app to watch for, in their own words, at decision time |
| **Score coverage or data-quality change** | A previously "unmeasured" pillar becomes measured and the score moves materially | Prevents acting on a stale, low-coverage score without knowing it improved (or got worse) |
| **Macro regime shift affecting a watched sector** | Policy rate cut → CoE falls → fair values move on rate-sensitive names you're watching | Directly extends the homepage's "macro → valuation" translation (already speced) into a push instead of requiring a daily visit |

### 3.3 Delivery: in-app notification center is the source of truth; push is the loud channel for the few things that deserve it

Two channels, not one, because "push notification" alone either becomes noise (if everything pushes) or gets silently missed (if nothing does):

1. **Notification center (bell icon, header, every screen)** — every alert lands here first, always, timestamped, filterable, marked read/unread. This is the audit trail and the calm default.
2. **Browser/OS push** (Web Push API + service worker — this is a web app, so this is the right mechanism rather than a native app store notification) — reserved for the two or three trigger types that are genuinely time-sensitive: **entered buy zone**, **thesis-breaker fired**, and **verdict downgrade on a held position**. Configurable per-user which trigger types push vs. stay in-app-only.
3. **Optional daily digest** (one email or one push, once, at a time the user sets — e.g. before market open) bundling everything from the last 24h into the "3 decisions today"-style summary already on the homepage. This directly serves the project's own "ultimate goal" (§22): *"a system I can open every morning and immediately understand..."* — the digest is that goal, delivered instead of visited.

Digest-first, real-time-second is also the behavioral-design-correct default: research on trading-app notification design specifically flags that always-on real-time alerts train reactive, anxious checking, while a bundled digest plus a short list of genuinely urgent pushes preserves signal without manufacturing urgency. [Source: TrendSpider — Instant Price Alerts](https://trendspider.com/learning-center/instant-price-alerts/); [Source: Open Web Solutions — Mobile Trading App Push Notifications for Active Trading](https://openwebsolutions.in/blog/mobile-trading-app-push-notifications-active-trading/)

### 3.4 Alert content — never just a number

Every push notification and every notification-center row follows one template, because a bare "NTB.N0000 hit 312.79" is exactly the kind of context-free trigger that produces impulsive action:

```
┌─────────────────────────────────────────────────────────┐
│ 🔔 NTB.N0000 entered your buy zone                       │
│ 314.00 → 312.50 (buy below 312.79)                       │
│ Score 74 · Fair value 347.55 · +11% to fair value        │
│ Your note when you added this: "watching for a pullback  │
│ toward buy-below"                                        │
│ [Open company]   [Record a decision →]                   │
└─────────────────────────────────────────────────────────┘
```

- Always restates **why you were watching it in the first place** (pulled straight from the Journal entry) — this is the contextual-anchoring pattern behavioral-design research recommends: your own past reasoning is a better anchor than the raw price alone. [Source: Open Web Solutions — Behavioral Design in Trading Apps](https://openwebsolutions.in/blog/behavioral-design-trading-apps-ux-patterns/)
- Always shows score + fair value + % to fair value alongside the price — never price in isolation, so the alert can't be mistaken for a pure technical trigger.
- Primary action is **"Record a decision"**, deep-linking to the Journal form pre-filled with this ticker and the trigger context in the reasoning field — every acted-on alert becomes an auditable, frozen decision record, closing the loop rather than living only as a transient notification. This is the "friction before the impulsive action" pattern from §0: not blocking the action, just routing it through the same disciplined form the rest of the product already requires.
- Downgrade/exit alerts use the **amber "blocked/caution" token** (`--blocked`, per the existing design-token spec) for the icon and border — never red, consistent with the app's existing rule that red is reserved and amber signals "pay attention," matching the calm, non-alarming palette already chosen for this product.

### 3.5 Frequency and noise control (this is the part that actually protects the user)

- **Per-ticker cooldown**: a given trigger type won't re-fire for the same ticker within a configurable window (default 24h) — a stock oscillating exactly on the buy-below line shouldn't produce ten notifications in an hour.
- **Digest bundling by default** for lower-urgency triggers (score/coverage changes, macro shifts) — only buy-zone entry, thesis-breaker, and downgrade-on-a-holding push immediately, per §3.3.
- **User-set quiet hours** — pushes queue silently into the notification center and the next digest instead of firing overnight.
- **A visible on/off per trigger type**, in settings, not just a global mute — some users will want every verdict change pushed, most won't; the default should be conservative (fewer, higher-signal pushes) and let the user opt into more, not the reverse.

This set of controls is deliberately closer to "protect the user's attention and discipline" than "maximize engagement" — consistent with the project's own stated priority of "long-term investment performance over flashy predictions" (project spec §22), and with the behavioral-finance research above showing that constant real-time alerting amplifies exactly the herd-behavior and FOMO patterns that hurt retail investors most. [Source: William & Mary — Behavioral Biases](https://online.mason.wm.edu/blog/behavioral-biases-that-can-impact-investing-decisions)

### 3.6 Data model sketch

```
watchlist_items (ticker, added_at, conviction, live_notes, journal_entry_id)
alert_rules     (id, ticker, user_id, trigger_type, threshold_override?, push_enabled, created_at)
alert_events    (id, rule_id, ticker, trigger_type, fired_at, snapshot_json, read_at, acted_on_journal_entry_id)
```

`snapshot_json` freezes the same kind of numbers the Journal already freezes (price, fair value, score, buy-below at fire time) — so a notification, once fired, doesn't silently reflect today's numbers if you open it three days later. Same "freeze at the moment" principle the Journal already applies, extended to alerts.

### 3.7 Build order

1. Wire the existing `⌘K` company search data source into a shared combobox component; apply it to the Journal ticker field first (highest-friction spot today), then Watchlist/Portfolio add-flows.
2. Ship the Watchlist screen read-only (roster + live numbers + near-buy-zone strip) sourced from existing `watchlist`-tagged Journal entries — no new triggers yet, just making the existing data visible as a live view instead of a buried log.
3. Add per-row quick actions (Open, Record decision, Set alert placeholder, Remove).
4. Build `alert_rules` / `alert_events` and the notification center (in-app only first — this alone delivers most of the value and needs no browser-permission plumbing).
5. Add Web Push (service worker + permission prompt, requested contextually — e.g. right after a user sets their first alert, never on first page load) for the three high-urgency trigger types.
6. Add the optional daily digest.
7. Add per-trigger-type settings and quiet hours.

---

## Sources

- [5 Behavioral Biases That Can Impact Your Investing Decisions — William & Mary](https://online.mason.wm.edu/blog/behavioral-biases-that-can-impact-investing-decisions)
- [Behavioral Design in Trading Apps: 9 UX Patterns for Better Decisions (2026) — Open Web Solutions](https://openwebsolutions.in/blog/behavioral-design-trading-apps-ux-patterns/)
- [Mobile Trading App Push Notifications for Active Trading — Open Web Solutions](https://openwebsolutions.in/blog/mobile-trading-app-push-notifications-active-trading/)
- [Instant Price Alerts — TrendSpider Learning Center](https://trendspider.com/learning-center/instant-price-alerts/)
- [Trading App Design: The Complete Guide to UI, UX & System Architecture (2026) — Lollypop](https://lollypop.design/blog/2026/june/trading-app-design/)
- [6 UX Design Best Practices for Autocomplete Suggestions — Coveo](https://www.coveo.com/blog/autocomplete-suggestions-ux-best-practices/)
- [Search autocomplete — a great UX practice — Bootcamp/UX Design](https://bootcamp.uxdesign.cc/search-autocomplete-a-great-ux-practice-d6370229b04b)
- Internal: `company-page-and-homepage-redesign.md` (design tokens, badge components, ⌘K search reference), `portfolio-page-redesign-spec.md` (row-popover pattern, attention-first ordering), `scoreboard-queue-redesign-spec.md` (precomputed-not-live principle, verdict badges)

*Fifth in the series. Prepared 2026-09-05.*
