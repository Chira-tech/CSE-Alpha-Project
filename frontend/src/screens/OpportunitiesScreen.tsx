import { useEffect, useState } from "react";
import { ApiRequestError, getOpportunityRanking } from "../api";
import { Delta } from "../components/Delta";
import { ErrorState, SkeletonTable } from "../components/states";
import { ZoneChip } from "../components/ZoneChip";
import { formatPrice, UNAVAILABLE } from "../format";
import type { OpportunityCandidate, OpportunityRanking } from "../types";

/**
 * §7.1 Opportunities: "the ranked board, the screener, the watchlist."
 *
 * §40 defines the target metric as risk-adjusted expected return net of
 * the cost of building the position, fed by the full §38 composite
 * score (valuation, business quality, growth, financial strength,
 * macro & sector fit, timing & momentum, risk, integrity veto) after
 * §39's sequential fusion. None of that exists yet — Piotroski/Altman/
 * Beneish/Sloan aren't wired into one score, Carhart certification and
 * the timing battery aren't built, and the earnings-integrity veto
 * isn't automated.
 *
 * What's real and live here: every ticker with CONFIRMED (not draft)
 * fundamentals, ranked by the real gap between its current price and
 * its real buy-below price from the price ladder (§25-26) — a genuine,
 * useful ordering, just not §40's full metric. See `app.domain.
 * opportunity_ranking_view`'s own module docstring on the backend for
 * the complete picture.
 */
export function OpportunitiesScreen() {
  const [data, setData] = useState<OpportunityRanking | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getOpportunityRanking()
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }, []);

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Opportunities</h1>
        <p className="prose">The ranked board, the screener, the watchlist.</p>
      </header>

      <div className="notice notice-neutral">
        <h3>A real, narrower ranking than §40's own target</h3>
        <p className="prose t-body">
          Ranked below by the real gap between each name's current price and its own real buy-below
          price (§25-26) — not yet §40's full risk-adjusted-return-net-of-costs metric, which needs
          the §38 composite score (business quality, growth, financial strength, macro fit, timing,
          integrity veto) that doesn't exist yet. Only tickers with CONFIRMED fundamentals are
          considered at all — a draft, AI-assisted figure never enters a ranking (§8).
        </p>
      </div>

      {error ? (
        <ErrorState
          whatFailed="The opportunity ranking could not be loaded"
          whatItAffects="This screen only."
          whatStillWorks="Every other screen, which reads independent data."
          whatHappensNext={`Check the API is running, then reload. Underlying error: ${error}`}
        />
      ) : !data ? (
        <SkeletonTable rows={6} columns={6} />
      ) : (
        <OpportunitiesBody data={data} />
      )}
    </div>
  );
}

function OpportunitiesBody({ data }: { data: OpportunityRanking }) {
  if (data.ranked.length === 0 && data.excluded.length === 0) {
    return (
      <div className="notice notice-neutral">
        <h3>No confirmed fundamentals yet</h3>
        <p className="prose t-body">
          This board fills in as fundamentals move through the confirm queue (Data health → Confirm
          queue) — nothing is ranked from unconfirmed, AI-assisted figures.
        </p>
      </div>
    );
  }

  return (
    <div className="stack-tight">
      <section aria-labelledby="ranked-heading" className="stack-tight">
        <h2 id="ranked-heading">Ranked</h2>
        {data.ranked.length === 0 ? (
          <div className="notice notice-neutral">
            <h3>Nothing ranks today</h3>
            <p className="prose t-body">
              Confirmed fundamentals exist, but none currently produce a computable price-ladder
              zone — see the excluded list below for exactly why, per name.
            </p>
          </div>
        ) : (
          <div className="table-wrap table-scroll">
            <table className="data-table">
              <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
                As of {data.as_of}. Sorted by gap to buy-below price — most below first.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Ticker</th>
                  <th scope="col" className="right">Price</th>
                  <th scope="col" className="right">Fair value</th>
                  <th scope="col">Zone</th>
                  <th scope="col" className="right">Buy below</th>
                  <th scope="col" className="right">Gap to buy below</th>
                </tr>
              </thead>
              <tbody>
                {data.ranked.map((c) => (
                  <CandidateRow key={c.ticker} c={c} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {data.excluded.length > 0 && (
        <details className="card-sunken">
          <summary className="t-data" style={{ cursor: "pointer" }}>
            {data.excluded.length} confirmed name{data.excluded.length === 1 ? "" : "s"} excluded from
            the ranking — real fundamentals, no computable zone
          </summary>
          <table className="data-table" style={{ marginTop: "var(--s3)" }}>
            <thead>
              <tr>
                <th scope="col">Ticker</th>
                <th scope="col">Why not</th>
              </tr>
            </thead>
            <tbody>
              {data.excluded.map((c) => (
                <tr key={c.ticker}>
                  <th scope="row" style={rowHeadStyle}>{c.ticker}</th>
                  <td className="muted">{c.warnings.join(" ") || UNAVAILABLE}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

function CandidateRow({ c }: { c: OpportunityCandidate }) {
  const gapPct = c.gap_to_buy_below_pct !== null ? Number(c.gap_to_buy_below_pct) * 100 : null;
  return (
    <tr>
      <th scope="row" style={rowHeadStyle}>{c.ticker}</th>
      <td className="right num">{c.current_price !== null ? formatPrice(c.current_price) : UNAVAILABLE}</td>
      <td className="right num">
        {c.blended_fair_value_per_share !== null ? formatPrice(c.blended_fair_value_per_share) : UNAVAILABLE}
      </td>
      <td>
        <ZoneChip zone={c.price_ladder_zone} />
      </td>
      <td className="right num">{c.buy_below_price !== null ? formatPrice(c.buy_below_price) : UNAVAILABLE}</td>
      <td className="right">
        {gapPct !== null ? <Delta percentage={gapPct} /> : <span className="muted">{UNAVAILABLE}</span>}
      </td>
    </tr>
  );
}

const rowHeadStyle = {
  background: "none",
  textTransform: "none" as const,
  letterSpacing: 0,
  fontSize: 13,
  fontWeight: 500,
  color: "var(--ink-1)",
};
