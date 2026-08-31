import { useEffect, useMemo, useState } from "react";
import {
  ApiRequestError,
  getCompositeRanking,
  getDataHealth,
  getMarketOverview,
  getPortfolioHoldingsValued,
  getSpread,
} from "../api";
import { DecisionsToday } from "../components/DecisionsToday";
import { Delta } from "../components/Delta";
import { MarketValuationHistogram } from "../components/MarketValuationHistogram";
import { ScoreBar } from "../components/ScoreBar";
import { SectorValueBars } from "../components/SectorValueBars";
import { TrustBar } from "../components/TrustBar";
import { VerdictChip } from "../components/VerdictChip";
import { ZoneChip } from "../components/ZoneChip";
import { EmptyState, ErrorState, SkeletonCard } from "../components/states";
import { directionOf, formatPrice, UNAVAILABLE } from "../format";
import type {
  CompositeRanking,
  DataHealth,
  MarketOverview,
  Spread,
  ValuedPortfolio,
} from "../types";

/**
 * UI & Experience Specification §8 — Screen 1 — rebuilt to the Company
 * Page & Homepage Redesign §6 information architecture. The screen's job
 * is not "what's happening in the market"; it is "where is price wrong
 * today, and can I trust that answer", read top to bottom:
 *
 *   1. Trust bar        — is the data behind everything below sound?
 *   2. Decisions today  — did any verdict actually change? (usually no)
 *   3. Three tiles      — my book · the market's valuation · the macro lever
 *   4. Is it cheap?     — price ÷ fair value across the universe, by sector
 *   5. Where to look    — best risk-adjusted names · positions to review
 *
 * Deliberately absent (redesign §6): top gainers / losers / most active.
 * They reward momentum and volatility, which is the opposite of what
 * this system is for, and they compete with the decisions list for the
 * top of the page. They belong on a Market tab.
 */
export function TodayScreen({
  onOpenScreen,
  onOpen,
}: {
  onOpenScreen: (id: "macro" | "portfolio" | "opportunities" | "review") => void;
  onOpen: (ticker: string) => void;
}) {
  const [market, setMarket] = useState<MarketOverview | null>(null);
  const [marketError, setMarketError] = useState<string | null>(null);
  const [health, setHealth] = useState<DataHealth | null | undefined>(undefined);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [spread, setSpread] = useState<Spread | null>(null);
  const [portfolio, setPortfolio] = useState<ValuedPortfolio | null | undefined>(undefined);
  const [ranking, setRanking] = useState<CompositeRanking | null | undefined>(undefined);
  const [rankingError, setRankingError] = useState<string | null>(null);

  useEffect(() => {
    getMarketOverview()
      .then(setMarket)
      .catch((e) => setMarketError(e instanceof ApiRequestError ? e.message : String(e)));
    getDataHealth()
      .then(setHealth)
      .catch((e) => {
        setHealth(null);
        setHealthError(e instanceof ApiRequestError ? e.message : String(e));
      });
    getSpread()
      .then(setSpread)
      .catch(() => setSpread(null));
    getPortfolioHoldingsValued()
      .then(setPortfolio)
      .catch(() => setPortfolio(null));
    getCompositeRanking()
      .then(setRanking)
      .catch((e) => {
        setRanking(null);
        setRankingError(e instanceof ApiRequestError ? e.message : String(e));
      });
  }, []);

  const heldTickers = useMemo(
    () => new Set((portfolio?.positions ?? []).map((p) => p.ticker)),
    [portfolio],
  );
  const knownTickers = useMemo(
    () => new Set((ranking?.ranked ?? []).map((r) => r.ticker)),
    [ranking],
  );

  // Market P/E as a percentile of its own history — "11.8×" means
  // nothing on its own; "62nd percentile of its own range" answers the
  // macro question a value investor actually has (redesign §6).
  const perPercentile = useMemo(() => {
    if (!spread || spread.market_per === null || spread.history.length < 8) return null;
    const cur = Number(spread.market_per);
    const hist = spread.history
      .map((h) => (Number(h.earnings_yield) > 0 ? 1 / Number(h.earnings_yield) : null))
      .filter((x): x is number => x !== null && Number.isFinite(x));
    if (hist.length < 8) return null;
    const below = hist.filter((x) => x <= cur).length;
    return { pct: Math.round((below / hist.length) * 100), n: hist.length };
  }, [spread]);

  // Real bp move in the risk-free rate over the tail of its own history —
  // the lever every cost of equity in the system sits on (redesign §6:
  // "express macro as its effect on fair value, not as a rate").
  const tbillMoveBp = useMemo(() => {
    if (!spread || spread.tbill_yield === null || spread.history.length < 6) return null;
    const now = Number(spread.tbill_yield);
    const past = Number(spread.history[Math.max(0, spread.history.length - 30)].tbill_yield);
    if (!Number.isFinite(now) || !Number.isFinite(past)) return null;
    return Math.round((now - past) * 10000);
  }, [spread]);

  const bestRiskAdjusted = useMemo(() => {
    if (!ranking) return [];
    const quarantined = new Set((health?.quarantined ?? []).map((q) => q.ticker));
    const noCall = new Set(["Withheld", "Insufficient data"]);
    return ranking.ranked
      .filter(
        (r) =>
          r.total_score !== null &&
          !quarantined.has(r.ticker) &&
          !noCall.has(r.verdict) &&
          r.discount_to_fair_value_pct !== null &&
          Number(r.discount_to_fair_value_pct) > 0,
      )
      .sort((a, b) => Number(b.total_score) - Number(a.total_score))
      .slice(0, 6);
  }, [ranking, health]);

  const needAttention = useMemo(() => {
    if (!portfolio) return [];
    return portfolio.positions
      .filter(
        (p) => p.attention_flags.length > 0 || p.price_ladder_zone === "exit" || p.price_ladder_zone === "trim",
      )
      .slice(0, 6);
  }, [portfolio]);

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

      {/* ---- 1. TRUST BAR ---------------------------------------------- */}
      {health === undefined ? (
        <SkeletonCard lines={1} />
      ) : healthError ? (
        <ErrorState
          whatFailed="The data-quality summary could not be loaded"
          whatItAffects="The trust bar only — the rest of this screen reads independent data."
          whatStillWorks="Companies, Portfolio and the confirm queues are unaffected."
          whatHappensNext={<>Check the API is reachable, then reload. Underlying error: {healthError}</>}
        />
      ) : health?.universe_status ? (
        <TrustBar
          status={health.universe_status}
          computedAt={ranking ? ranking.computed_at : undefined}
          stale={ranking?.is_stale}
        />
      ) : null}

      {/* ---- 2. DECISIONS TODAY (hero) ------------------------------- */}
      <section aria-labelledby="decisions-heading" className="stack-tight">
        <h2 id="decisions-heading">Decisions today</h2>
        {ranking === undefined ? (
          <SkeletonCard lines={2} />
        ) : rankingError ? (
          <ErrorState
            whatFailed="The composite ranking could not be loaded"
            whatItAffects="The decisions list, the valuation histogram and the best-risk-adjusted table."
            whatStillWorks="The trust bar, portfolio summary and market tiles read independent data."
            whatHappensNext={<>Check the API is running, then reload. Underlying error: {rankingError}</>}
          />
        ) : (
          <DecisionsToday
            insights={ranking?.insights ?? []}
            tickers={knownTickers}
            onOpen={onOpen}
            historyAvailable={Boolean(ranking?.snapshot_available)}
          />
        )}
      </section>

      {/* ---- 3. THREE TILES ---------------------------------------- */}
      <section aria-labelledby="tiles-heading" className="stack-tight">
        <h2 id="tiles-heading">Where things stand</h2>
        <div className="stat-grid">
          {/* Portfolio */}
          <div className="card">
            <span className="t-label">Portfolio</span>
            {portfolio === undefined ? (
              <SkeletonCard lines={2} />
            ) : portfolio === null ? (
              <>
                <p className="t-body prose" style={{ marginTop: "var(--s2)" }}>
                  No holdings uploaded yet.
                </p>
                <button onClick={() => onOpenScreen("portfolio")}>Go to Portfolio</button>
              </>
            ) : (
              <>
                <div className="stat-value">
                  {portfolio.total_live_market_value !== null
                    ? formatPrice(portfolio.total_live_market_value)
                    : UNAVAILABLE}
                </div>
                {portfolio.total_live_market_value !== null &&
                  (() => {
                    const gain =
                      Number(portfolio.total_live_market_value) - Number(portfolio.total_cost);
                    const gainPct = (gain / Number(portfolio.total_cost)) * 100;
                    return (
                      <div className={`delta delta-${directionOf(gain)}`} style={{ marginTop: "var(--s1)" }}>
                        <Delta percentage={gainPct} /> unrealised
                      </div>
                    );
                  })()}
                <p className="t-caption" style={{ marginTop: "var(--s2)" }}>
                  {portfolio.positions.length} position{portfolio.positions.length === 1 ? "" : "s"}
                  {needAttention.length > 0 ? ` · ${needAttention.length} need review` : ""}
                </p>
                <button onClick={() => onOpenScreen("portfolio")}>Open Portfolio</button>
              </>
            )}
          </div>

          {/* Market valuation */}
          <div className="card">
            <span className="t-label">Market valuation</span>
            {marketError && !spread ? (
              <p className="t-caption" style={{ marginTop: "var(--s2)" }}>
                Live market feed unavailable.
              </p>
            ) : (
              <>
                <div className="stat-value">
                  {market?.aspi?.value != null
                    ? `ASPI ${market.aspi.value.toLocaleString("en-GB", { maximumFractionDigits: 0 })}`
                    : UNAVAILABLE}
                </div>
                {market?.aspi?.percentage != null && (
                  <div style={{ marginTop: "var(--s1)" }}>
                    <Delta percentage={market.aspi.percentage} />
                  </div>
                )}
                <p className="t-caption prose" style={{ marginTop: "var(--s2)" }}>
                  {spread?.market_per != null
                    ? `Market P/E ${Number(spread.market_per).toFixed(1)}×`
                    : "Market P/E unavailable"}
                  {perPercentile
                    ? ` — ${perPercentile.pct}th percentile of its own ${perPercentile.n}-observation history`
                    : ""}
                  .
                </p>
              </>
            )}
          </div>

          {/* Macro → valuations */}
          <div className="card">
            <span className="t-label">Macro → valuations</span>
            {spread?.tbill_yield != null ? (
              <>
                <div className="stat-value">
                  Risk-free {(Number(spread.tbill_yield) * 100).toFixed(2)}%
                  {tbillMoveBp !== null && tbillMoveBp !== 0 && (
                    <span style={{ fontSize: 13, fontWeight: 500, marginLeft: "var(--s2)", color: "var(--ink-3)" }}>
                      {tbillMoveBp > 0 ? "▲" : "▼"} {Math.abs(tbillMoveBp)}bp
                    </span>
                  )}
                </div>
                <p className="t-caption prose" style={{ marginTop: "var(--s2)" }}>
                  The 364-day T-bill is the base of every cost of equity in the system. When it
                  {tbillMoveBp !== null && tbillMoveBp < 0 ? " falls, as now, " : " moves, "}
                  every fair value re-rates the other way. The regime read and its sector tilts live
                  on{" "}
                  <button className="btn-link" onClick={() => onOpenScreen("macro")}>
                    Macro
                  </button>
                  .
                </p>
              </>
            ) : (
              <p className="t-caption" style={{ marginTop: "var(--s2)" }}>
                No risk-free observation available yet.
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ---- 4. IS THE MARKET CHEAP? ------------------------------- */}
      <section aria-labelledby="cheap-heading" className="stack-tight">
        <h2 id="cheap-heading">Is the market cheap, and where?</h2>
        {ranking === undefined ? (
          <SkeletonCard lines={4} />
        ) : !ranking || ranking.ranked.length === 0 ? (
          <EmptyState title="No universe ranking yet">
            <p style={{ margin: 0 }}>
              The scheduled composite pass has not produced a snapshot with fair values yet.
            </p>
          </EmptyState>
        ) : (
          <div className="today-duo">
            <div className="card">
              <span className="t-label">Price ÷ fair value, whole universe</span>
              <div style={{ marginTop: "var(--s3)" }}>
                <MarketValuationHistogram rows={ranking.ranked} holdings={heldTickers} />
              </div>
            </div>
            <div className="card">
              <span className="t-label">Median discount to fair value, by sector</span>
              <div style={{ marginTop: "var(--s3)" }}>
                <SectorValueBars rows={ranking.ranked} />
              </div>
            </div>
          </div>
        )}
      </section>

      {/* ---- 5. WHERE TO LOOK ------------------------------------- */}
      <section aria-labelledby="look-heading" className="stack-tight">
        <h2 id="look-heading">Where to look</h2>
        <div className="today-duo">
          <div className="card">
            <span className="t-label">Best risk-adjusted · cheap &amp; not quarantined</span>
            {ranking === undefined ? (
              <SkeletonCard lines={3} />
            ) : bestRiskAdjusted.length === 0 ? (
              <p className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
                Nothing currently scores well AND trades below its blended fair value. That is a
                legitimate state — the system is not obliged to find a buy every day.
              </p>
            ) : (
              <div className="table-wrap" style={{ marginTop: "var(--s3)" }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Ticker</th>
                      <th scope="col" className="right">Score</th>
                      <th scope="col" className="right">Fair value</th>
                      <th scope="col" className="right">Upside</th>
                      <th scope="col">Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bestRiskAdjusted.map((r) => (
                      <tr key={r.ticker} className="selectable" onClick={() => onOpen(r.ticker)}>
                        <th scope="row" style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>
                          {r.ticker}
                        </th>
                        <td className="right">
                          <ScoreBar score={Number(r.total_score)} width={96} />
                        </td>
                        <td className="right num">
                          {r.blended_fair_value_per_share !== null
                            ? formatPrice(r.blended_fair_value_per_share)
                            : UNAVAILABLE}
                        </td>
                        <td className="right">
                          <Delta percentage={Number(r.discount_to_fair_value_pct) * 100} />
                        </td>
                        <td>
                          <VerdictChip verdict={r.verdict} confidence={r.decision_confidence} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {ranking && (
              <button style={{ marginTop: "var(--s3)" }} onClick={() => onOpenScreen("opportunities")}>
                Open Opportunities
              </button>
            )}
          </div>

          <div className="card">
            <span className="t-label">Positions needing attention</span>
            {portfolio === undefined ? (
              <SkeletonCard lines={3} />
            ) : portfolio === null ? (
              <p className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
                No holdings uploaded — nothing to review.
              </p>
            ) : needAttention.length === 0 ? (
              <p className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
                No held position is in the trim or exit zone and none carries an attention flag.
              </p>
            ) : (
              <div className="table-wrap" style={{ marginTop: "var(--s3)" }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Ticker</th>
                      <th scope="col">Zone</th>
                      <th scope="col" className="right">Unrealised</th>
                      <th scope="col">Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {needAttention.map((p) => {
                      const pl =
                        p.live_unrealized_gain_loss !== null && Number(p.total_cost) !== 0
                          ? (Number(p.live_unrealized_gain_loss) / Number(p.total_cost)) * 100
                          : null;
                      return (
                        <tr key={p.ticker} className="selectable" onClick={() => onOpen(p.ticker)}>
                          <th scope="row" style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>
                            {p.ticker}
                          </th>
                          <td>
                            <ZoneChip zone={p.price_ladder_zone} />
                          </td>
                          <td className="right">
                            {pl !== null ? <Delta percentage={pl} /> : <span className="muted">{UNAVAILABLE}</span>}
                          </td>
                          <td className="t-caption">
                            {p.attention_flags[0]?.label ??
                              (p.price_ladder_zone === "exit" ? "In the exit zone" : "In the trim zone")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {portfolio && (
              <button style={{ marginTop: "var(--s3)" }} onClick={() => onOpenScreen("portfolio")}>
                Open Portfolio
              </button>
            )}
          </div>
        </div>
      </section>

      {market && (
        <p className="t-caption">
          Market figures fetched {new Date(market.fetched_at).toLocaleTimeString()}
          {market.cached ? " (cached, at most once a minute)" : ""} · live passthrough from cse.lk,
          not stored · composite scores from{" "}
          {ranking?.computed_at
            ? `a run at ${new Date(ranking.computed_at).toLocaleString()}`
            : "a live pass (no scheduled snapshot yet)"}
          .
        </p>
      )}
    </div>
  );
}
