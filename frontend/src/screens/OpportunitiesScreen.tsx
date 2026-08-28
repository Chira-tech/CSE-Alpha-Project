import { useEffect, useState } from "react";
import { ApiRequestError, getOpportunityRanking } from "../api";
import { Delta } from "../components/Delta";
import { PaginationControls, usePagination } from "../components/PaginatedTable";
import { ErrorState, SkeletonTable } from "../components/states";
import { ZoneChip } from "../components/ZoneChip";
import { formatPrice, UNAVAILABLE } from "../format";
import type { OpportunityCandidate, OpportunityRanking } from "../types";

const PAGE_SIZE_OPTIONS = [10, 15, 20, 30] as const;
const DEFAULT_PAGE_SIZE = 15;

/**
 * §7.1 Opportunities: "the ranked board, the screener, the watchlist."
 *
 * §40 defines the target metric as risk-adjusted expected return net of
 * the cost of building the position, fed by the full §38 composite
 * score (valuation, business quality, growth, financial strength,
 * macro & sector fit, timing & momentum, risk, integrity veto) after
 * §39's sequential fusion. The composite score itself is real now, live
 * per-company on the company file (`GET /composite-score/{ticker}`) —
 * Carhart certification and the timing battery are both built and
 * folded into it. What §39's sequential fusion into ONE ranked list
 * here still needs: the composite score computed for the WHOLE universe
 * on some schedule (today it's a real ~30s pass per request, too slow
 * to repeat for every row of this screen — see `app.domain.
 * composite_score_view`'s own docstring), and the earnings-integrity
 * veto is still not automated (Piotroski/Altman/Beneish/Sloan aren't
 * wired anywhere in this system).
 *
 * What's real and live here: every ticker with CONFIRMED (not draft)
 * fundamentals, ranked by the real gap between its current price and
 * its real buy-below price from the price ladder (§25-26) — a genuine,
 * useful ordering, just not §40's full metric. See `app.domain.
 * opportunity_ranking_view`'s own module docstring on the backend for
 * the complete picture.
 */
export function OpportunitiesScreen({ onOpen }: { onOpen: (ticker: string) => void }) {
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
          Ranked by the real gap between each name's current price and its own real buy-below price
          (§25-26) — a research shortlist, not §40's full risk-adjusted-return metric and not a
          recommendation to trade.
        </p>
        <details style={{ marginTop: "var(--s2)" }}>
          <summary className="t-caption" style={{ cursor: "pointer" }}>
            What's still missing, and why
          </summary>
          <p className="prose t-body" style={{ marginTop: "var(--s2)" }}>
            The §38 composite score itself is real now (open any company file to see it) — what's
            still missing here is running it across the WHOLE universe to rank by (a real ~30s pass
            per ticker, too slow to repeat for every row of this screen) and the automated
            earnings-integrity veto. Only tickers with CONFIRMED fundamentals are considered at all
            — a draft, AI-assisted figure never enters a ranking (§8).
          </p>
        </details>
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
        <OpportunitiesBody data={data} onOpen={onOpen} />
      )}
    </div>
  );
}

function OpportunitiesBody({ data, onOpen }: { data: OpportunityRanking; onOpen: (ticker: string) => void }) {
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
          <RankedTable ranked={data.ranked} asOf={data.as_of} onOpen={onOpen} />
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
                  <th scope="row" style={rowHeadStyle}>
                    <button className="btn-link mono" onClick={() => onOpen(c.ticker)}>
                      {c.ticker}
                    </button>
                  </th>
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

/** R1 T4.2.2 — the ranked list gets the same real page-size selector +
 * previous/next + "showing X-Y of Z" every long table gets. Client-side
 * (the ranking is already fetched in full — `PaginatedTable.tsx`'s own
 * docstring explains why that's the right form here, vs. `Fundamentals
 * Queue`'s server-side paging). */
function RankedTable({
  ranked,
  asOf,
  onOpen,
}: {
  ranked: OpportunityCandidate[];
  asOf: string;
  onOpen: (ticker: string) => void;
}) {
  const { page, pageSize, offset, total, setPageSize, goToPrevious, goToNext } = usePagination(
    ranked,
    DEFAULT_PAGE_SIZE,
  );
  return (
    <div className="stack-tight">
      <div className="table-wrap table-scroll">
        <table className="data-table">
          <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
            As of {asOf}. Sorted by gap to buy-below price — most below first.
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
            {page.map((c) => (
              <CandidateRow key={c.ticker} c={c} onOpen={onOpen} />
            ))}
          </tbody>
        </table>
      </div>
      <PaginationControls
        total={total}
        offset={offset}
        pageSize={pageSize}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        shownCount={page.length}
        onPageSizeChange={setPageSize}
        onPrevious={goToPrevious}
        onNext={goToNext}
      />
    </div>
  );
}

function CandidateRow({ c, onOpen }: { c: OpportunityCandidate; onOpen: (ticker: string) => void }) {
  const gapPct = c.gap_to_buy_below_pct !== null ? Number(c.gap_to_buy_below_pct) * 100 : null;
  return (
    <tr>
      <th scope="row" style={rowHeadStyle}>
        <button className="btn-link mono" onClick={() => onOpen(c.ticker)}>
          {c.ticker}
        </button>
      </th>
      <td className="right num">{c.current_price !== null ? formatPrice(c.current_price) : UNAVAILABLE}</td>
      <td className="right num">
        {c.blended_fair_value_per_share !== null ? formatPrice(c.blended_fair_value_per_share) : UNAVAILABLE}
      </td>
      <td>
        <ZoneChip zone={c.price_ladder_zone} why={c.warnings.join(" ") || undefined} />
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
