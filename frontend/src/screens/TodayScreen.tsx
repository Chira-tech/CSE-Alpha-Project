import { useEffect, useState } from "react";
import {
  ApiRequestError,
  getDataHealth,
  getIndexHistory,
  getMarketOverview,
  getOpportunityRanking,
  getPortfolioHoldingsValued,
  getSpread,
} from "../api";
import { Delta } from "../components/Delta";
import { SpreadHero } from "../components/SpreadHero";
import { TrendChip } from "../components/TrendChip";
import { ZoneChip } from "../components/ZoneChip";
import { EmptyState, ErrorState, PartialNotice, SkeletonCard } from "../components/states";
import { directionOf, formatIndexValue, formatInteger, formatPrice, trendWindowPct, UNAVAILABLE } from "../format";
import type { DataHealth, IndexHistory, MarketOverview, OpportunityRanking, Spread, ValuedPortfolio } from "../types";

/**
 * UI & Experience Specification §8 — Screen 1, "Today". Four questions in
 * descending order of importance.
 *
 * WHERE AM I? (§3) reads the same real holdings valuation the Portfolio
 * screen shows — a one-line summary here, the full breakdown there.
 * WHAT IS ON THE BOARD? (§4) does the same against the Opportunities
 * screen's real ranking — §40's own full risk-adjusted-return metric
 * still needs engines that don't exist yet (named on Opportunities
 * itself), but the real, narrower gap-to-buy-below ranking that DOES
 * exist belongs here too, not hidden behind a stale "not built" notice.
 *
 * §7.2's governing constraint on this screen: it "must be fully readable
 * in under two minutes and must usually conclude with 'nothing to do'."
 * Section 2 below is written to reach that conclusion plainly when
 * there's genuinely nothing pending.
 */
export function TodayScreen({
  onOpenScreen,
}: {
  onOpenScreen: (id: "macro" | "portfolio" | "opportunities" | "review") => void;
}) {
  const [market, setMarket] = useState<MarketOverview | null>(null);
  const [marketError, setMarketError] = useState<string | null>(null);
  const [health, setHealth] = useState<DataHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [spread, setSpread] = useState<Spread | null>(null);
  const [portfolio, setPortfolio] = useState<ValuedPortfolio | null | undefined>(undefined);
  const [opportunities, setOpportunities] = useState<OpportunityRanking | null | undefined>(undefined);
  const [aspiHistory, setAspiHistory] = useState<IndexHistory | null>(null);
  // TASK 2.1 (product-owner brief): this preview card shows 5 ranked
  // opportunities with a "Show 5 more" that APPENDS rather than paginates
  // away — deliberately not `usePagination`/`PaginationControls`
  // (`components/PaginatedTable.tsx`), which is the right shape for the
  // full Opportunities screen's own table but a "Previous" control makes
  // no sense on a homepage teaser card that only ever grows.
  const [boardShown, setBoardShown] = useState(5);

  useEffect(() => {
    getMarketOverview()
      .then(setMarket)
      .catch((e) => setMarketError(e instanceof ApiRequestError ? e.message : String(e)));
    // T4.1.2's TrendChip — real ASPI history, independent of the live
    // market call above so one failing doesn't take the other down.
    getIndexHistory()
      .then(setAspiHistory)
      .catch(() => setAspiHistory(null));
    getDataHealth()
      .then(setHealth)
      .catch((e) => setHealthError(e instanceof ApiRequestError ? e.message : String(e)));
    // The spread reads the local database, so it survives the CSE feed
    // being unreachable — it is deliberately not tied to the market call.
    getSpread()
      .then(setSpread)
      .catch(() => setSpread(null));
    getPortfolioHoldingsValued()
      .then(setPortfolio)
      .catch(() => setPortfolio(null));
    getOpportunityRanking()
      .then(setOpportunities)
      .catch(() => setOpportunities(null));
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
        {/* R1 T4.1.1 */}
        <h1>Today's summary</h1>
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
              {aspiHistory && aspiHistory.points.length > 1 && (
                <div style={{ marginTop: "var(--s3)" }}>
                  <TrendChip
                    windows={[15, 30, 45].map((n) => ({
                      label: `${n}d`,
                      pct: trendWindowPct(aspiHistory.points, n),
                    }))}
                  />
                </div>
              )}
            </div>

            {spread && <SpreadHero spread={spread} />}

            <div className="notice notice-neutral">
              <h3>The regime gauge lives on Macro</h3>
              <p className="prose t-body">
                It is real and live now: the blended read, the two independent sub-reads behind it
                (a Markov switching fit on ASPI returns and a rule-based macro composite), what the
                current regime is already doing to every fair value in the system, §30's
                error-correction half-life, and the §33 sector tilts that are statistically
                significant right now. Two parts of it are still genuinely missing and say so
                there — a recommended gross exposure (§31 names exposure-capping but gives no
                number for it, and there is no portfolio-sizing layer for one to act on) and
                validation against a real historical Sri Lankan regime, which this system's own
                macro series aren't deep enough for yet.{" "}
                <button className="btn-link" onClick={() => onOpenScreen("macro")}>
                  Open the regime gauge
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
            {health.fundamentals_pending_by_ticker.length > 0 && (
              <p className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
                Highest-count tickers in the queue:{" "}
                {health.fundamentals_pending_by_ticker
                  .slice(0, 5)
                  .map((t) => `${t.ticker} (${t.count})`)
                  .join(", ")}
                .
              </p>
            )}
            <div style={{ marginTop: "var(--s4)" }}>
              <button onClick={() => onOpenScreen("review")}>Open the confirm queue</button>
            </div>
          </div>
        )}
      </section>

      <section aria-labelledby="where-heading" className="stack-tight">
        <h2 id="where-heading">3 · Where am I?</h2>
        {portfolio === null ? (
          <div className="notice notice-neutral">
            <h3>No portfolio uploaded yet</h3>
            <p className="prose t-body">
              Upload a real CDS/broker holdings export to see your current positions valued against
              this system's own fair-value engine.
            </p>
            <div style={{ marginTop: "var(--s4)" }}>
              <button onClick={() => onOpenScreen("portfolio")}>Go to Portfolio</button>
            </div>
          </div>
        ) : portfolio === undefined ? (
          <SkeletonCard lines={2} />
        ) : (
          <div className="card">
            <div style={{ display: "flex", gap: "var(--s6)", flexWrap: "wrap", alignItems: "baseline" }}>
              <div>
                <span className="t-label">Cost</span>
                <div className="t-data">{formatPrice(portfolio.total_cost)}</div>
              </div>
              <div>
                <span className="t-label">Live value</span>
                <div className="t-data">
                  {portfolio.total_live_market_value !== null
                    ? formatPrice(portfolio.total_live_market_value)
                    : UNAVAILABLE}
                </div>
              </div>
              {portfolio.total_live_market_value !== null &&
                (() => {
                  const gain = Number(portfolio.total_live_market_value) - Number(portfolio.total_cost);
                  const gainPct = (gain / Number(portfolio.total_cost)) * 100;
                  return (
                    <div>
                      <span className="t-label">Unrealised P&amp;L</span>
                      <div className={`t-data delta delta-${directionOf(gain)}`}>
                        <Delta percentage={gainPct} />
                      </div>
                    </div>
                  );
                })()}
              <div>
                <span className="t-label">Positions</span>
                <div className="t-data">{portfolio.positions.length}</div>
              </div>
            </div>
            {/* R1 T4.1.6: FOUR windows here specifically (not three like
                Portfolio's own summary) — the brief's own instruction. */}
            <div style={{ marginTop: "var(--s4)" }}>
              <TrendChip
                windows={["15d", "30d", "45d", "60d"].map((label) => ({
                  label,
                  pct: portfolio.value_trend_pct[label] !== null && portfolio.value_trend_pct[label] !== undefined
                    ? Number(portfolio.value_trend_pct[label])
                    : null,
                }))}
              />
            </div>
            <div style={{ marginTop: "var(--s4)" }}>
              <button onClick={() => onOpenScreen("portfolio")}>Open Portfolio</button>
            </div>
          </div>
        )}
      </section>

      <section aria-labelledby="board-heading" className="stack-tight">
        <h2 id="board-heading">4 · What is on the board?</h2>
        {opportunities === null ? (
          <div className="notice notice-neutral">
            <h3>The board could not be loaded</h3>
            <p className="prose t-body">
              Check the API is running, then reload — every other section on this screen reads
              independent data.
            </p>
          </div>
        ) : opportunities === undefined ? (
          <SkeletonCard lines={2} />
        ) : opportunities.ranked.length === 0 ? (
          <div className="notice notice-neutral">
            <h3>Nothing ranks yet</h3>
            <p className="prose t-body">
              §40's full risk-adjusted-return ranking still isn't built — the §38 composite score
              itself is real now (see any company file), but blending it into a ranked list here
              needs a universe-wide pass this system doesn't yet run on a schedule — see{" "}
              <button className="btn-link" onClick={() => onOpenScreen("opportunities")}>
                Opportunities
              </button>{" "}
              for the real, narrower ranking this system can compute today, and why nothing
              qualifies yet.
            </p>
          </div>
        ) : (
          <div className="card">
            <p className="t-caption" style={{ margin: "0 0 var(--s3)" }}>
              Real gap-to-buy-below ranking (§25-26) — not yet §40's full risk-adjusted-return metric,
              see Opportunities for what's still missing.
            </p>
            <div className="table-wrap table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Ticker</th>
                    <th scope="col" className="right">Price</th>
                    <th scope="col">Zone</th>
                    <th scope="col" className="right">Gap to buy below</th>
                  </tr>
                </thead>
                <tbody>
                  {opportunities.ranked.slice(0, boardShown).map((c) => (
                    <tr key={c.ticker}>
                      <th scope="row" style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>
                        {c.ticker}
                      </th>
                      <td className="right num">{c.current_price !== null ? formatPrice(c.current_price) : UNAVAILABLE}</td>
                      <td>
                        <ZoneChip zone={c.price_ladder_zone} why={c.warnings.join(" ") || undefined} />
                      </td>
                      <td className="right">
                        {c.gap_to_buy_below_pct !== null ? (
                          <Delta percentage={Number(c.gap_to_buy_below_pct) * 100} />
                        ) : (
                          <span className="muted">{UNAVAILABLE}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row" style={{ marginTop: "var(--s4)", gap: "var(--s3)" }}>
              {boardShown < opportunities.ranked.length && (
                <button onClick={() => setBoardShown((n) => n + 5)}>
                  Show 5 more ({opportunities.ranked.length - boardShown} remaining)
                </button>
              )}
              <button onClick={() => onOpenScreen("opportunities")}>
                Open Opportunities ({opportunities.ranked.length} ranked)
              </button>
            </div>
          </div>
        )}
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
