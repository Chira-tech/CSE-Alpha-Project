import { useEffect, useMemo, useState } from "react";
import { ApiRequestError, getCompositeRanking, getOpportunityRanking } from "../api";
import { CompositeInsightsStrip } from "../components/CompositeInsightsStrip";
import { Delta } from "../components/Delta";
import { PaginationControls, usePagination } from "../components/PaginatedTable";
import { ScoreBar } from "../components/ScoreBar";
import { ScoreDistribution } from "../components/ScoreDistribution";
import { SectorScoreHeatmap } from "../components/SectorScoreHeatmap";
import { Sparkline } from "../components/Sparkline";
import { AsOf, ErrorState, SkeletonTable } from "../components/states";
import { VerdictChip } from "../components/VerdictChip";
import { ZoneChip } from "../components/ZoneChip";
import { formatPrice, UNAVAILABLE } from "../format";
import type {
  CompositeRanking,
  OpportunityCandidate,
  OpportunityRanking,
  RankedComposite,
} from "../types";

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} h ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

const PAGE_SIZE_OPTIONS = [10, 15, 20, 30] as const;
// TASK 2.1 (product-owner brief): "Opportunities tab: 20, sorted best
// rank first" — 20 is the specified default; 15 stayed as an option.
const DEFAULT_PAGE_SIZE = 20;

/**
 * §7.1 Opportunities: "the ranked board, the screener, the watchlist."
 *
 * §40 defines the target metric as risk-adjusted expected return net of
 * the cost of building the position, fed by the full §38 composite
 * score (valuation, business quality, growth, financial strength,
 * macro & sector fit, timing & momentum, risk, integrity veto) after
 * §39's sequential fusion.
 *
 * The §38 composite score is now computed across the WHOLE confirmed
 * universe and ranked here — one cached ~30s pass (`GET
 * /composite-ranking`, same disclosed-TTL cache as `/opportunities`),
 * so unlike the single-ticker company-file score the Valuation pillar
 * is actually blended (ranked against the rest of the universe). That
 * is the primary table below. What §40 still needs on top of it: §39's
 * sequential fusion, the transaction-cost leg of the metric, and an
 * automated §14 earnings-integrity veto (Piotroski/Altman/Beneish/Sloan
 * — not wired anywhere yet, so integrity is carried on every row as
 * `evaluable: false` but never applied as a filter).
 *
 * The secondary table keeps the older, narrower ordering: every ticker
 * with CONFIRMED (not draft) fundamentals, ranked by the real gap
 * between its current price and its real buy-below price from the price
 * ladder (§25-26). See `app.domain.composite_ranking_view` and
 * `app.domain.opportunity_ranking_view`'s own docstrings for the
 * complete picture.
 */
export function OpportunitiesScreen({ onOpen }: { onOpen: (ticker: string) => void }) {
  const [data, setData] = useState<OpportunityRanking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [composite, setComposite] = useState<CompositeRanking | null>(null);
  const [compositeError, setCompositeError] = useState<string | null>(null);

  useEffect(() => {
    getOpportunityRanking()
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
    getCompositeRanking()
      .then(setComposite)
      .catch((e) => setCompositeError(e instanceof ApiRequestError ? e.message : String(e)));
  }, []);

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Opportunities</h1>
        <p className="prose">The ranked board, the screener, the watchlist.</p>
      </header>

      <div className="notice notice-neutral">
        <h3>Ranked by the §38 composite score — still narrower than §40's own target</h3>
        <p className="prose t-body">
          The primary table is every CONFIRMED-fundamentals ticker (§8) scored on §38's seven
          weighted pillars and ranked by the blended total. It is not yet §40's full
          risk-adjusted-return-net-of-cost metric and not a recommendation to trade.
        </p>
        <details style={{ marginTop: "var(--s2)" }}>
          <summary className="t-caption" style={{ cursor: "pointer" }}>
            What's still missing, and why
          </summary>
          <p className="prose t-body" style={{ marginTop: "var(--s2)" }}>
            The §38 composite score is now run across the WHOLE universe on one cached ~30s pass, so
            the Valuation pillar is ranked and blended here (the single-ticker company-file score
            still shows it as evidence only, to keep that page fast). What remains before this is
            §40's full metric: §39's sequential fusion, the transaction-cost leg, and an automated
            §14 earnings-integrity veto (Piotroski/Altman/Beneish/Sloan) — none of it wired yet, so
            integrity is carried on every row as unevaluable but never applied as a filter. The
            Growth pillar also stays excluded until at least three tickers have a confirmed
            national-projects revenue impact to rank against.
          </p>
        </details>
      </div>

      <section aria-labelledby="composite-heading" className="stack-tight">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "var(--s3)", flexWrap: "wrap" }}>
          <h2 id="composite-heading">Ranked by §38 composite score</h2>
          {composite && (
            <AsOf
              stale={composite.is_stale}
              label={
                composite.computed_at
                  ? `Last computed ${relativeTime(composite.computed_at)}${composite.is_stale ? " — market has moved since" : ""}`
                  : "Computed live — no scheduled snapshot yet"
              }
            />
          )}
        </div>
        {compositeError ? (
          <ErrorState
            whatFailed="The §38 composite ranking could not be loaded"
            whatItAffects="This table only — the discount ranking below loads independently."
            whatStillWorks="Every other screen, and the secondary ranking below."
            whatHappensNext={`Check the API is running, then reload. Underlying error: ${compositeError}`}
          />
        ) : !composite ? (
          <SkeletonTable rows={6} columns={6} />
        ) : (
          <CompositeRankingBody data={composite} onOpen={onOpen} />
        )}
      </section>

      <section aria-labelledby="discount-heading" className="stack-tight">
        <h2 id="discount-heading">Ranked by discount to buy-below price</h2>
        <p className="prose t-body">
          A narrower, older ordering kept alongside the composite score: the real gap between each
          name's current price and its own real buy-below price from the price ladder (§25-26).
        </p>
        {error ? (
          <ErrorState
            whatFailed="The discount ranking could not be loaded"
            whatItAffects="This table only."
            whatStillWorks="Every other screen, and the composite ranking above."
            whatHappensNext={`Check the API is running, then reload. Underlying error: ${error}`}
          />
        ) : !data ? (
          <SkeletonTable rows={6} columns={6} />
        ) : (
          <OpportunitiesBody data={data} onOpen={onOpen} />
        )}
      </section>
    </div>
  );
}

const PILLAR_COLUMNS: { key: string; short: string }[] = [
  { key: "valuation", short: "Val" },
  { key: "business_quality", short: "Quality" },
  { key: "growth", short: "Growth" },
  { key: "financial_strength", short: "Fin" },
  { key: "macro_sector_fit", short: "Macro" },
  { key: "timing_momentum", short: "Timing" },
  { key: "risk", short: "Risk" },
];

function formatScore(score: string | null): string {
  return score !== null ? Math.round(Number(score)).toString() : UNAVAILABLE;
}

function CompositeRankingBody({
  data,
  onOpen,
}: {
  data: CompositeRanking;
  onOpen: (ticker: string) => void;
}) {
  if (data.ranked.length === 0 && data.excluded.length === 0) {
    return (
      <div className="notice notice-neutral">
        <h3>No confirmed fundamentals yet</h3>
        <p className="prose t-body">
          This board fills in as fundamentals move through the confirm queue (Data health → Confirm
          queue) — nothing is scored from unconfirmed, AI-assisted figures.
        </p>
      </div>
    );
  }

  const rankedScores = data.ranked
    .map((r) => (r.total_score !== null ? Number(r.total_score) : NaN))
    .filter((n) => Number.isFinite(n));

  return (
    <div className="stack-tight">
      <CompositeInsightsStrip insights={data.insights} snapshotAvailable={data.snapshot_available} />

      {data.ranked.length === 0 ? (
        <div className="notice notice-neutral">
          <h3>Nothing scores today</h3>
          <p className="prose t-body">
            Confirmed fundamentals exist, but no ticker has a single computable §38 pillar yet — see
            the excluded list below for exactly why, per name.
          </p>
        </div>
      ) : (
        <>
          <div
            className="card"
            style={{ display: "grid", gap: "var(--s5)", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}
          >
            <ScoreDistribution scores={rankedScores} />
            <SectorScoreHeatmap rows={data.ranked} />
          </div>
          <CompositeRankedTable ranked={data.ranked} asOf={data.as_of} onOpen={onOpen} />
        </>
      )}

      {data.excluded.length > 0 && (
        <details className="card-sunken">
          <summary className="t-data" style={{ cursor: "pointer" }}>
            {data.excluded.length} confirmed name{data.excluded.length === 1 ? "" : "s"} not scored —
            quarantined, or no computable pillar yet
          </summary>
          <table className="data-table" style={{ marginTop: "var(--s3)" }}>
            <thead>
              <tr>
                <th scope="col">Ticker</th>
                <th scope="col">Why not</th>
              </tr>
            </thead>
            <tbody>
              {data.excluded.map((r) => (
                <tr key={r.ticker}>
                  <th scope="row" style={rowHeadStyle}>
                    <button className="btn-link mono" onClick={() => onOpen(r.ticker)}>
                      {r.ticker}
                    </button>
                  </th>
                  <td className="muted">
                    {r.warnings.join(" ") ||
                      r.pillars.find((p) => !p.included)?.reason ||
                      UNAVAILABLE}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

const ALL = "__all__";

function CompositeRankedTable({
  ranked,
  asOf,
  onOpen,
}: {
  ranked: RankedComposite[];
  asOf: string;
  onOpen: (ticker: string) => void;
}) {
  const [sector, setSector] = useState<string>(ALL);
  const [verdict, setVerdict] = useState<string>(ALL);
  const [minBasis, setMinBasis] = useState<number>(1);

  const sectors = useMemo(
    () => [...new Set(ranked.map((r) => r.cse_sector).filter((s): s is string => !!s))].sort(),
    [ranked],
  );
  const verdicts = useMemo(
    () => [...new Set(ranked.map((r) => r.verdict))].sort(),
    [ranked],
  );

  const filtered = useMemo(
    () =>
      ranked.filter(
        (r) =>
          (sector === ALL || r.cse_sector === sector) &&
          (verdict === ALL || r.verdict === verdict) &&
          r.pillars_included >= minBasis,
      ),
    [ranked, sector, verdict, minBasis],
  );

  const { page, pageSize, offset, total, setPageSize, goToPrevious, goToNext } = usePagination(
    filtered,
    DEFAULT_PAGE_SIZE,
  );

  return (
    <div className="stack-tight">
      <div className="row" style={{ gap: "var(--s3)", flexWrap: "wrap", alignItems: "flex-end" }}>
        <label className="t-caption" style={{ display: "grid", gap: "var(--s1)" }}>
          Sector
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value={ALL}>All</option>
            {sectors.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="t-caption" style={{ display: "grid", gap: "var(--s1)" }}>
          Verdict
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            <option value={ALL}>All</option>
            {verdicts.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </label>
        <label className="t-caption" style={{ display: "grid", gap: "var(--s1)" }}>
          Min basis
          <select value={minBasis} onChange={(e) => setMinBasis(Number(e.target.value))}>
            <option value={1}>Any</option>
            <option value={4}>≥ 4 / 7</option>
            <option value={6}>≥ 6 / 7</option>
          </select>
        </label>
        {filtered.length !== ranked.length && (
          <span className="t-caption muted">
            {filtered.length} of {ranked.length} shown
          </span>
        )}
      </div>

      <div className="table-wrap table-scroll table-scroll--pinned">
        <table className="data-table">
          <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
            As of {asOf}. Sorted by the blended §38 composite score, highest first. “Basis” is how
            many of the 7 pillars fed the score — a 2-pillar score and a 7-pillar score at the same
            number are not equally corroborated. Open a row (›) for the full pillar breakdown, each
            pillar's reason, and the valuation evidence. Verdict is the decision engine's own call,
            not a label derived from the score. Integrity (§11.1 / §14) is not scored anywhere yet
            and is not applied as a filter here.
          </caption>
          <thead>
            <tr>
              <th scope="col">Ticker</th>
              <th scope="col">Composite</th>
              <th scope="col" className="right">Basis</th>
              <th scope="col">Verdict</th>
              <th scope="col">Score trend</th>
            </tr>
          </thead>
          <tbody>
            {page.map((r) => (
              <CompositeRow key={r.ticker} r={r} onOpen={onOpen} />
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

function CompositeRow({ r, onOpen }: { r: RankedComposite; onOpen: (ticker: string) => void }) {
  const [open, setOpen] = useState(false);
  const spark = r.score_series.map((p) => Number(p.total_score));

  return (
    <>
      <tr>
        <th scope="row" style={rowHeadStyle}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--s1)" }}>
            <button
              className="btn-link"
              aria-expanded={open}
              aria-label={open ? `Hide ${r.ticker} breakdown` : `Show ${r.ticker} breakdown`}
              onClick={() => setOpen((o) => !o)}
              style={{ fontFamily: "var(--font-mono)", color: "var(--ink-3)", width: "1.2em" }}
            >
              {open ? "⌄" : "›"}
            </button>
            <button className="btn-link mono" onClick={() => onOpen(r.ticker)}>
              {r.ticker}
            </button>
          </span>
        </th>
        <td>
          <ScoreBar score={r.total_score !== null ? Number(r.total_score) : null} />
        </td>
        <td
          className="right num"
          title={`Pillars covering ${Math.round(Number(r.weight_covered_pct))}% of §38's intended weight fed this score`}
        >
          <span className={r.pillars_included <= 3 ? "muted" : undefined}>{r.pillars_included}/7</span>
        </td>
        <td>
          <VerdictChip verdict={r.verdict} confidence={r.decision_confidence} />
        </td>
        <td>
          {spark.length >= 2 ? (
            <Sparkline values={spark} label={`${r.ticker} composite score, recent snapshots`} />
          ) : (
            <span className="muted" title="needs at least two scheduled snapshots">—</span>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} style={{ background: "var(--surface-sunken)", padding: "var(--s3) var(--s4)" }}>
            <CompositeRowDetail r={r} />
          </td>
        </tr>
      )}
    </>
  );
}

function CompositeRowDetail({ r }: { r: RankedComposite }) {
  const byKey = new Map(r.pillars.map((p) => [p.key, p]));
  return (
    <div style={{ display: "grid", gap: "var(--s3)" }}>
      <div style={{ display: "grid", gap: "var(--s2)" }}>
        <span className="t-label">Pillar breakdown</span>
        {PILLAR_COLUMNS.map((c) => {
          const p = byKey.get(c.key);
          const weightUsed = r.weight_used_pct[c.key];
          return (
            <div
              key={c.key}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 9rem) 170px 3rem 1fr",
                alignItems: "center",
                gap: "var(--s2)",
              }}
            >
              <span className="t-caption">{p?.label ?? c.short}</span>
              <ScoreBar score={p && p.included ? Number(p.score) : null} compact width={170} />
              <span className="t-caption num" style={{ textAlign: "right" }}>
                {p && p.included ? formatScore(p.score) : <span className="muted">{UNAVAILABLE}</span>}
              </span>
              <span className="t-caption muted">
                {p && p.included
                  ? weightUsed
                    ? `${Math.round(Number(weightUsed))}% of the score`
                    : ""
                  : p?.reason ?? ""}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: "var(--s6)", flexWrap: "wrap" }}>
        <Evidence label="Fair value" value={r.blended_fair_value_per_share !== null ? formatPrice(r.blended_fair_value_per_share) : UNAVAILABLE} />
        <Evidence label="Current price" value={r.current_price !== null ? formatPrice(r.current_price) : UNAVAILABLE} />
        <Evidence
          label="Discount to fair value"
          value={
            r.discount_to_fair_value_pct !== null
              ? `${(Number(r.discount_to_fair_value_pct) * 100).toFixed(0)}%`
              : UNAVAILABLE
          }
        />
        <Evidence
          label="Valuation percentile"
          value={r.valuation_pillar_percentile !== null ? formatScore(r.valuation_pillar_percentile) : UNAVAILABLE}
        />
      </div>

      <p className="t-caption muted" style={{ margin: 0 }}>
        Integrity: {r.integrity.reason}
      </p>
    </div>
  );
}

function Evidence({ label, value }: { label: string; value: string }) {
  return (
    <span className="t-caption">
      <span className="t-label">{label}</span>
      <br />
      <span className="num">{value}</span>
    </span>
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
      <div className="table-wrap table-scroll table-scroll--pinned">
        <table className="data-table">
          <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
            As of {asOf}. Sorted by decision confidence first (high, then medium, then low), gap
            to buy-below price only as the tie-breaker within a confidence tier — a real, live
            audit (30 Aug 2026) found sorting by discount alone let thin, single-anchor reads
            dominate the top of this list. Every candidate here has also passed a real §11.1 Gate 1
            liquidity check; a stock too thinly traded to buy at any meaningful size is excluded
            regardless of its discount to fair value.
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
