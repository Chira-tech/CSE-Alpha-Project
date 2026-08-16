import { useEffect, useState } from "react";
import { ApiRequestError, getDataHealth, getMarketOverview } from "../api";
import { Delta } from "../components/Delta";
import { EmptyState, ErrorState, PartialNotice, SkeletonCard } from "../components/states";
import { formatIndexValue, formatInteger } from "../format";
import type { DataHealth, MarketOverview } from "../types";

/**
 * UI & Experience Specification §8 — Screen 1, "Today". Four questions in
 * descending order of importance.
 *
 * Two of the four (WHERE AM I? — portfolio; WHAT IS ON THE BOARD? — the
 * ranked list) need engines that don't exist yet, and are shown as
 * explicit gaps rather than empty cards, per §17's placeholder
 * prohibition.
 *
 * §7.2's governing constraint on this screen: it "must be fully readable
 * in under two minutes and must usually conclude with 'nothing to do'."
 * Section 2 below is written to reach that conclusion plainly when
 * there's genuinely nothing pending.
 */
export function TodayScreen({ onOpenScreen }: { onOpenScreen: (id: "macro" | "review") => void }) {
  const [market, setMarket] = useState<MarketOverview | null>(null);
  const [marketError, setMarketError] = useState<string | null>(null);
  const [health, setHealth] = useState<DataHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  useEffect(() => {
    getMarketOverview()
      .then(setMarket)
      .catch((e) => setMarketError(e instanceof ApiRequestError ? e.message : String(e)));
    getDataHealth()
      .then(setHealth)
      .catch((e) => setHealthError(e instanceof ApiRequestError ? e.message : String(e)));
  }, []);

  const attention: string[] = [];
  if (health) {
    if (health.corporate_actions_pending > 0) {
      attention.push(
        `${health.corporate_actions_pending} corporate action${health.corporate_actions_pending === 1 ? "" : "s"} awaiting confirmation`,
      );
    }
    if (health.fundamentals_pending_confirmation > 0) {
      attention.push(
        `${health.fundamentals_pending_confirmation} extracted financial figure${health.fundamentals_pending_confirmation === 1 ? "" : "s"} awaiting confirmation`,
      );
    }
    if (health.quarantined.length > 0) {
      attention.push(
        `${health.quarantined.length} ticker${health.quarantined.length === 1 ? "" : "s"} quarantined by a data-quality alert`,
      );
    }
    if (health.price_feed_age_days !== null && health.price_feed_age_days > 2) {
      attention.push(`Price data is ${health.price_feed_age_days} days old`);
    }
  }

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Today</h1>
        <p className="prose">
          {new Date().toLocaleDateString("en-GB", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric",
          })}
        </p>
      </header>

      {/* ---- 1. WHAT IS THE WEATHER? ------------------------------- */}
      <section aria-labelledby="weather-heading" className="stack-tight">
        <h2 id="weather-heading">1 · What is the weather?</h2>

        {marketError ? (
          <ErrorState
            whatFailed="The market overview could not be loaded"
            whatItAffects="Index levels and sector performance on this screen only."
            whatStillWorks="Everything served from the local database — Companies, Data health and the confirm queues — is unaffected."
            whatHappensNext={
              <>
                This screen reads the CSE feed live. Check the API is running at{" "}
                <span className="code-hint">http://localhost:8000</span>, then reload. Underlying
                error: {marketError}
              </>
            }
          />
        ) : !market ? (
          <SkeletonCard lines={3} />
        ) : (
          <>
            {market.unavailable.length > 0 && <PartialNotice sections={market.unavailable} />}
            <div className="card">
              <span className="t-label">All Share Price Index</span>
              <div className="hero-value">{formatIndexValue(market.aspi?.value)}</div>
              <div className="row" style={{ marginTop: "var(--s2)" }}>
                <Delta percentage={market.aspi?.percentage} />
                <span className="t-caption">
                  day range {formatIndexValue(market.aspi?.low)} – {formatIndexValue(market.aspi?.high)}
                </span>
                {market.status && <span className="status-tag">{market.status}</span>}
              </div>
            </div>

            <div className="notice notice-neutral">
              <h3>The regime read is not built yet — Phase 5</h3>
              <p className="prose t-body">
                The spec puts the earnings-yield-minus-364-day-T-bill spread on this screen, not the
                index level, and calls it "the single most powerful macro variable in the system"
                (§29): CSE equity is priced as a substitute for Treasury bills, so the index tells
                you what happened while the spread tells you whether equities are cheap against the
                only real alternative. The index above is a stand-in until the macro engine exists.{" "}
                <button className="btn-link" onClick={() => onOpenScreen("macro")}>
                  What Macro will contain
                </button>
              </p>
            </div>
          </>
        )}
      </section>

      {/* ---- 2. WHAT NEEDS MY ATTENTION? ---------------------------- */}
      <section aria-labelledby="attention-heading" className="stack-tight">
        <h2 id="attention-heading">2 · What needs my attention?</h2>
        {healthError ? (
          <ErrorState
            whatFailed="The attention list could not be loaded"
            whatItAffects="This section only."
            whatStillWorks="The rest of this screen, and every other screen."
            whatHappensNext={<>Check the API is reachable, then reload. Underlying error: {healthError}</>}
          />
        ) : !health ? (
          <SkeletonCard lines={2} />
        ) : attention.length === 0 ? (
          <EmptyState title="Nothing needs your attention.">
            <p style={{ margin: 0 }}>
              No pending confirmations, no quarantined tickers, and the price feed is current. On a
              normal day this section should read exactly like this — a 12–36 month strategy should
              not demand daily action.
            </p>
          </EmptyState>
        ) : (
          <div className="card">
            <ul style={{ margin: 0, paddingLeft: "var(--s5)" }}>
              {attention.map((line) => (
                <li key={line} className="t-body" style={{ marginBottom: "var(--s1)" }}>
                  {line}
                </li>
              ))}
            </ul>
            <div style={{ marginTop: "var(--s4)" }}>
              <button onClick={() => onOpenScreen("review")}>Open the confirm queue</button>
            </div>
          </div>
        )}
      </section>

      {/* ---- 3 and 4: not built ------------------------------------- */}
      <section aria-labelledby="where-heading" className="stack-tight">
        <h2 id="where-heading">3 · Where am I?</h2>
        <div className="notice notice-neutral">
          <h3>Portfolio tracking is not built yet — Phase 8</h3>
          <p className="prose t-body">
            Holdings, thesis status, factor exposure against target and distance to each exit trigger
            live here (§41–42). It depends on the decision record having captured frozen model state
            at purchase, which in turn depends on there being a model to freeze.
          </p>
        </div>
      </section>

      <section aria-labelledby="board-heading" className="stack-tight">
        <h2 id="board-heading">4 · What is on the board?</h2>
        <div className="notice notice-neutral">
          <h3>The ranked board is not built yet — Phases 2–3</h3>
          <p className="prose t-body">
            The top names by composite score, each with price, buy-below, gap and agreement
            indicator (§40). Needs the fundamental, valuation and price engines. Until then,{" "}
            <strong>Companies</strong> lists the full universe with the real market data that does
            exist.
          </p>
        </div>
      </section>

      {market && (
        <p className="t-caption">
          Market figures fetched {new Date(market.fetched_at).toLocaleTimeString()}
          {market.cached ? " (cached, refreshes at most once a minute)" : ""} · live passthrough from
          cse.lk, not stored and not point-in-time · {formatInteger(health?.securities_count ?? null)}{" "}
          companies in the local store
        </p>
      )}
    </div>
  );
}
