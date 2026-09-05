import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiRequestError, createDecision, getCompositeRanking, listDecisions, recordOutcome } from "../api";
import { Delta } from "../components/Delta";
import { ErrorState, SkeletonCard } from "../components/states";
import { TickerCombobox } from "../components/TickerCombobox";
import { VerdictChip } from "../components/VerdictChip";
import { formatPercent, formatPrice, UNAVAILABLE } from "../format";
import type { Decision, DecisionAction, RankedComposite, SecurityListItem } from "../types";

const ACTIONS: DecisionAction[] = ["buy", "watchlist", "pass", "partial", "sell", "trim"];

/**
 * §7.1 Journal: "every decision I made and how it turned out."
 *
 * §45's own words on why this ships even though most of the layers it
 * references don't exist yet: "Every decision you make without a
 * recorded rationale is a data point you can never recover... start
 * recording the day you can see a price and a score, even if the score
 * is only the fundamental one."
 *
 * What's real and frozen at decision time: the blended fair value, the
 * price ladder (buy-below / fair value / trim-above), the margin-of-
 * safety breakdown, and the live price. What's honestly absent on every
 * row today: the §38 composite score, §36 Carhart certification and §37
 * timing are all real and computable now (`GET /composite-score/
 * {ticker}`), but this capture step doesn't read them yet, so the
 * columns their own schema already has stay empty on every decision —
 * named per-field in `app.models.decisions`'s own docstring on the
 * backend, not silently omitted from the schema.
 */
export function JournalScreen() {
  const [decisions, setDecisions] = useState<Decision[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ranking, setRanking] = useState<RankedComposite[] | null>(null);

  function load() {
    listDecisions()
      .then(setDecisions)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }

  useEffect(load, []);
  // Independent of the decisions load above — a watched ticker still
  // shows (with price/verdict unavailable) if this call fails, rather
  // than the whole screen erroring out over a panel that's secondary to
  // the journal itself.
  useEffect(() => {
    getCompositeRanking()
      .then((r) => setRanking(r.ranked))
      .catch(() => setRanking([]));
  }, []);

  // "Currently watching" = every ticker whose MOST RECENT decision
  // (any action) is still `watchlist` — a later buy/sell/pass on the
  // same ticker retires it from here without touching the append-only
  // history below, exactly the "live view over a frozen log" split
  // §2.2 of the redesign spec asks for.
  const watching = useMemo(() => {
    if (!decisions) return null;
    const latestByTicker = new Map<string, Decision>();
    for (const d of decisions) {
      const prev = latestByTicker.get(d.ticker);
      if (!prev || new Date(d.timestamp) > new Date(prev.timestamp)) latestByTicker.set(d.ticker, d);
    }
    return [...latestByTicker.values()]
      .filter((d) => d.action === "watchlist")
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [decisions]);

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Journal</h1>
        <p className="prose">Every decision I made and how it turned out.</p>
      </header>

      <div className="notice notice-neutral">
        <h3>What gets frozen today, and what doesn't yet</h3>
        <p className="prose t-body">
          Every decision below freezes this system's own real fair value, price ladder and margin-of-
          safety breakdown at the moment you record it — never edited afterwards. Still honestly
          absent from every row: the §38 composite score, §36 Carhart certification and §37 timing
          battery — all three are real and computable now (open any company file), this capture step
          just doesn't read them into a decision yet. Recording now, even with that gap, is the whole
          point (§45): a decision without a recorded rationale is a data point you can never recover
          later.
        </p>
      </div>

      <RecordDecisionForm onRecorded={load} />

      <WatchlistPanel watching={watching} ranking={ranking} />

      {error ? (
        <ErrorState
          whatFailed="The decision journal could not be loaded"
          whatItAffects="This screen only."
          whatStillWorks="Every other screen, which reads independent data."
          whatHappensNext={`Check the API is running, then reload. Underlying error: ${error}`}
        />
      ) : !decisions ? (
        <SkeletonCard lines={3} />
      ) : decisions.length === 0 ? (
        <div className="notice notice-neutral">
          <h3>No decisions recorded yet</h3>
          <p className="prose t-body">Use the form above the first time you can see a price and a fair value for a name.</p>
        </div>
      ) : (
        <div className="stack-tight">
          {decisions.map((d) => (
            <DecisionCard key={d.id} decision={d} onOutcomeRecorded={load} />
          ))}
        </div>
      )}
    </div>
  );
}

function RecordDecisionForm({ onRecorded }: { onRecorded: () => void }) {
  const [ticker, setTicker] = useState("");
  // The ticker of the last row actually PICKED from the dropdown. Reset
  // to null on every keystroke, so editing after a pick un-confirms it —
  // the point is to stop a typo from ever reaching a frozen record, so
  // "was once matched" isn't good enough if the text has since changed.
  const [confirmedTicker, setConfirmedTicker] = useState<string | null>(null);
  const [confirmedName, setConfirmedName] = useState<string | null>(null);
  const [action, setAction] = useState<DecisionAction>("watchlist");
  const [reasoning, setReasoning] = useState("");
  const [falsification, setFalsification] = useState("");
  const [conviction, setConviction] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tickerConfirmed = confirmedTicker !== null && confirmedTicker === ticker.trim().toUpperCase();

  function onTickerSelect(item: SecurityListItem) {
    setTicker(item.ticker);
    setConfirmedTicker(item.ticker);
    setConfirmedName(item.name);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!tickerConfirmed) return; // belt-and-braces — the button is already disabled for this
    setSubmitting(true);
    setError(null);
    try {
      await createDecision({
        ticker: ticker.trim().toUpperCase(),
        action,
        reasoning_text: reasoning.trim(),
        falsification_text: falsification.trim() || undefined,
        conviction_1_5: conviction ? Number(conviction) : undefined,
      });
      setTicker("");
      setConfirmedTicker(null);
      setConfirmedName(null);
      setReasoning("");
      setFalsification("");
      setConviction("");
      onRecorded();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="card stack-tight">
      <h2 style={{ margin: 0 }}>Record a decision</h2>
      <div style={{ display: "flex", gap: "var(--s3)", flexWrap: "wrap" }}>
        <div className="field" style={{ flex: "1 1 220px" }}>
          <label htmlFor="j-ticker" className="t-label">Ticker</label>
          <TickerCombobox
            id="j-ticker"
            value={ticker}
            placeholder="Type a ticker or company name…"
            required
            onChange={(text) => {
              setTicker(text);
              if (confirmedTicker && text.trim().toUpperCase() !== confirmedTicker) {
                setConfirmedTicker(null);
                setConfirmedName(null);
              }
            }}
            onSelect={onTickerSelect}
          />
          <p className="t-caption" style={{ margin: 0, color: tickerConfirmed ? "var(--ink-3)" : "var(--caution)" }}>
            {tickerConfirmed
              ? confirmedName
              : ticker.trim().length > 0
                ? "Pick a match from the dropdown to enable recording — free text alone can't be saved."
                : "Start typing to search the confirmed security list."}
          </p>
        </div>
        <div className="field" style={{ flex: "0 1 160px" }}>
          <label htmlFor="j-action" className="t-label">Action</label>
          <select id="j-action" value={action} onChange={(e) => setAction(e.target.value as DecisionAction)}>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ flex: "0 1 140px" }}>
          <label htmlFor="j-conviction" className="t-label">Conviction (1-5)</label>
          <select id="j-conviction" value={conviction} onChange={(e) => setConviction(e.target.value)}>
            <option value="">—</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="field">
        <label htmlFor="j-reasoning" className="t-label">Reasoning</label>
        <textarea
          id="j-reasoning" value={reasoning} onChange={(e) => setReasoning(e.target.value)} required
          placeholder="Why this action, right now?"
        />
      </div>
      <div className="field">
        <label htmlFor="j-falsification" className="t-label">
          What would prove me wrong? (§45 — the highest-value field on this form)
        </label>
        <textarea
          id="j-falsification" value={falsification} onChange={(e) => setFalsification(e.target.value)}
          placeholder='Specific and checkable, e.g. "net interest margin below 3.4% for two consecutive quarters" — not "if fundamentals deteriorate".'
        />
      </div>
      {error && (
        <p className="prose t-body" style={{ color: "var(--neg)" }}>
          Could not record this decision: {error}
        </p>
      )}
      <div>
        <button
          type="submit"
          className="btn-primary"
          disabled={submitting || !tickerConfirmed}
          title={!tickerConfirmed ? "Pick a ticker from the dropdown first" : undefined}
        >
          {submitting ? "Recording…" : "Record decision"}
        </button>
      </div>
    </form>
  );
}

/**
 * §2 of the redesign spec's gap: "the only way to see your watchlist is
 * to scroll the Journal looking for rows tagged watchlist." This is the
 * live, quick-glance answer to "what am I currently watching, and how's
 * it doing" — sourced from the same append-only decisions the Journal
 * already records, not a new stored list. Deliberately minimal: no
 * near-buy-zone strip, no quick actions, no alerts — just price, verdict
 * and score per name, today.
 */
function WatchlistPanel({
  watching,
  ranking,
}: {
  watching: Decision[] | null;
  ranking: RankedComposite[] | null;
}) {
  if (watching === null) return null; // decisions still loading — the list above already shows a skeleton
  if (watching.length === 0) return null; // nothing watched — no need for an empty card under a form that's right there

  const byTicker = new Map((ranking ?? []).map((r) => [r.ticker, r]));

  return (
    <div className="card stack-tight">
      <h2 style={{ margin: 0 }}>Watching ({watching.length})</h2>
      <p className="prose t-caption" style={{ margin: 0 }}>
        Tickers whose most recent journal entry is still "watchlist" — a later buy, sell or pass
        removes a name from here without touching its history below.
      </p>
      <div className="table-wrap table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Ticker</th>
              <th scope="col">Verdict</th>
              <th scope="col" className="right">Price</th>
              <th scope="col" className="right">Fair value</th>
              <th scope="col" className="right">Since watched</th>
            </tr>
          </thead>
          <tbody>
            {watching.map((d) => {
              const r = byTicker.get(d.ticker);
              const days = Math.max(0, Math.floor((Date.now() - new Date(d.timestamp).getTime()) / 86_400_000));
              return (
                <tr key={d.ticker}>
                  <th scope="row" className="mono">{d.ticker}</th>
                  <td>{r ? <VerdictChip verdict={r.verdict} confidence={r.decision_confidence} /> : <span className="muted">{UNAVAILABLE}</span>}</td>
                  <td className="right num">{r?.current_price ? formatPrice(r.current_price) : UNAVAILABLE}</td>
                  <td className="right num">
                    {r?.blended_fair_value_per_share ? formatPrice(r.blended_fair_value_per_share) : UNAVAILABLE}
                  </td>
                  <td className="right t-caption">{days === 0 ? "today" : `${days}d`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DecisionCard({ decision, onOutcomeRecorded }: { decision: Decision; onOutcomeRecorded: () => void }) {
  return (
    <div className="card stack-tight">
      <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: "var(--s2)" }}>
        <div>
          <span className="chip" style={{ marginRight: "var(--s2)" }}>{decision.action}</span>
          <strong>{decision.ticker}</strong>
          {decision.conviction_1_5 !== null && (
            <span className="t-caption" style={{ marginLeft: "var(--s2)" }}>
              Conviction {decision.conviction_1_5}/5
            </span>
          )}
        </div>
        <span className="t-caption">{new Date(decision.timestamp).toLocaleString()}</span>
      </div>

      <p className="prose t-body" style={{ margin: 0 }}>{decision.reasoning_text}</p>
      {decision.falsification_text && (
        <p className="prose t-caption" style={{ margin: 0 }}>
          <strong>What would prove this wrong:</strong> {decision.falsification_text}
        </p>
      )}

      <div className="table-wrap table-scroll">
        <table className="data-table">
          <tbody>
            <tr>
              <td style={{ color: "var(--ink-3)" }}>Market price at decision</td>
              <td className="right num">
                {decision.market_price_at_decision !== null ? formatPrice(decision.market_price_at_decision) : UNAVAILABLE}
              </td>
              <td style={{ color: "var(--ink-3)" }}>Blended fair value</td>
              <td className="right num">{decision.fv_blended !== null ? formatPrice(decision.fv_blended) : UNAVAILABLE}</td>
            </tr>
            <tr>
              <td style={{ color: "var(--ink-3)" }}>Buy below</td>
              <td className="right num">{decision.buy_below !== null ? formatPrice(decision.buy_below) : UNAVAILABLE}</td>
              <td style={{ color: "var(--ink-3)" }}>Trim above</td>
              <td className="right num">{decision.trim_above !== null ? formatPrice(decision.trim_above) : UNAVAILABLE}</td>
            </tr>
            <tr>
              <td style={{ color: "var(--ink-3)" }}>Macro regime</td>
              <td className="right">{decision.macro_regime ?? UNAVAILABLE}</td>
              <td style={{ color: "var(--ink-3)" }}>Regime probability</td>
              <td className="right num">
                {decision.macro_prob !== null ? formatPercent(Number(decision.macro_prob) * 100) : UNAVAILABLE}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {decision.fv_by_method_json && Object.keys(decision.fv_by_method_json).length > 0 && (
        <details>
          <summary className="t-caption" style={{ cursor: "pointer" }}>
            Fair value by method ({Object.keys(decision.fv_by_method_json).length})
          </summary>
          <ul className="not-built-list">
            {Object.entries(decision.fv_by_method_json).map(([method, value]) => (
              <li key={method}>
                {method}: {formatPrice(value)}
              </li>
            ))}
          </ul>
        </details>
      )}

      {decision.outcome ? (
        <div className="notice notice-neutral" style={{ padding: "var(--s3)" }}>
          <p className="prose t-body" style={{ margin: 0 }}>
            Exited {decision.outcome.exit_date} at {formatPrice(decision.outcome.exit_price)} (
            {decision.outcome.exit_trigger}), held {decision.outcome.holding_days} days.
          </p>
          <div style={{ display: "flex", gap: "var(--s4)", marginTop: "var(--s2)" }}>
            <span>
              Gross <Delta percentage={Number(decision.outcome.gross_return) * 100} />
            </span>
            <span>
              Net (after §2.1's round-trip cost) <Delta percentage={Number(decision.outcome.net_return) * 100} />
            </span>
          </div>
        </div>
      ) : (
        <RecordOutcomeForm decision={decision} onRecorded={onOutcomeRecorded} />
      )}
    </div>
  );
}

function RecordOutcomeForm({ decision, onRecorded }: { decision: Decision; onRecorded: () => void }) {
  const [open, setOpen] = useState(false);
  const [exitDate, setExitDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [exitPrice, setExitPrice] = useState("");
  const [exitTrigger, setExitTrigger] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <div>
        <button onClick={() => setOpen(true)}>Record outcome</button>
      </div>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await recordOutcome(decision.id, { exit_date: exitDate, exit_price: exitPrice, exit_trigger: exitTrigger });
      onRecorded();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack-tight" style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--s3)" }}>
      <div style={{ display: "flex", gap: "var(--s3)", flexWrap: "wrap", alignItems: "end" }}>
        <div className="field" style={{ flex: "0 1 160px" }}>
          <label className="t-label">Exit date</label>
          <input type="date" value={exitDate} onChange={(e) => setExitDate(e.target.value)} required />
        </div>
        <div className="field" style={{ flex: "0 1 120px" }}>
          <label className="t-label">Exit price</label>
          <input type="number" step="0.01" value={exitPrice} onChange={(e) => setExitPrice(e.target.value)} required />
        </div>
        <div className="field" style={{ flex: "1 1 200px" }}>
          <label className="t-label">Exit trigger</label>
          <input
            type="text" value={exitTrigger} onChange={(e) => setExitTrigger(e.target.value)} required
            placeholder="e.g. hit buy-below-derived target, thesis broken"
          />
        </div>
        <button type="submit" disabled={submitting}>
          {submitting ? "Recording…" : "Save outcome"}
        </button>
      </div>
      {error && (
        <p className="prose t-body" style={{ color: "var(--neg)" }}>
          Could not record this outcome: {error}
        </p>
      )}
    </form>
  );
}
