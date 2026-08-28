import { useEffect, useState } from "react";
import {
  ApiRequestError,
  getCompositeScore,
  getMonteCarlo,
  getScenarios,
  getSecurity,
  getSecurityPrices,
  getTornado,
  getValuation,
} from "../api";
import { EvidencePanel, type Evidence } from "../components/EvidencePanel";
import { FundamentalsLinesTable } from "../components/FundamentalsLinesTable";
import { PlainExplainer } from "../components/PlainExplainer";
import { PriceHistoryChart } from "../components/PriceHistoryChart";
import { PriceLadder } from "../components/PriceLadder";
import { RatioCardGrid } from "../components/RatioCardGrid";
import { EmptyState, ErrorState, QuarantineNotice, SkeletonCard } from "../components/states";
import { VerdictPill, verdictFromPercentile } from "../components/VerdictPill";
import { formatAgo, formatMagnitude, formatPrice, UNAVAILABLE } from "../format";
import type {
  CompanyValuation,
  CompositeScore,
  MonteCarlo,
  PillarScore,
  PriceHistoryPage,
  PricePoint,
  ScenarioSet,
  SecurityDetail,
  Tornado,
} from "../types";

/** The price-history table is paged server-side (`GET
 * /securities/{ticker}/prices`, SQL limit/offset) rather than loading a
 * year-plus of daily rows and slicing client-side — a company with a
 * year of daily rows would otherwise make this the single largest
 * response on the page for a table showing five rows at a time. */
const PRICE_PAGE_SIZE_OPTIONS = [5, 10, 25, 50] as const;
const DEFAULT_PRICE_PAGE_SIZE = 5;

const rowHeadStyle = {
  background: "none",
  textTransform: "none" as const,
  letterSpacing: 0,
  fontSize: 13,
  fontWeight: 500,
  color: "var(--ink-1)",
};

const ACTION_LABELS: Record<string, string> = {
  dividend_cash: "Cash dividend",
  bonus_issue: "Bonus issue",
  rights_issue: "Rights issue",
  stock_split: "Stock split",
  consolidation: "Consolidation",
  delisting: "Delisting",
  suspension: "Suspension",
};

export function CompanyScreen({
  ticker,
  onBack,
  onOpen,
  backLabel = "All companies",
}: {
  ticker: string;
  onBack: () => void;
  /** Jump to another line of the same issuer. */
  onOpen: (ticker: string) => void;
  /** A ticker can be drilled into from Companies, Portfolio or
   * Opportunities alike — the back link names wherever this one actually
   * came from rather than always claiming "All companies". */
  backLabel?: string;
}) {
  const [data, setData] = useState<SecurityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [valuation, setValuation] = useState<CompanyValuation | null>(null);
  const [valuationError, setValuationError] = useState<string | null>(null);
  const [composite, setComposite] = useState<CompositeScore | null>(null);
  const [compositeError, setCompositeError] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioSet | null>(null);
  const [scenariosError, setScenariosError] = useState<string | null>(null);
  const [tornado, setTornado] = useState<Tornado | null>(null);
  const [monteCarlo, setMonteCarlo] = useState<MonteCarlo | null>(null);
  const [monteCarloLoading, setMonteCarloLoading] = useState(false);
  const [monteCarloError, setMonteCarloError] = useState<string | null>(null);
  const [pricePage, setPricePage] = useState<PriceHistoryPage | null>(null);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [pricePageSize, setPricePageSize] = useState<number>(DEFAULT_PRICE_PAGE_SIZE);
  const [priceOffset, setPriceOffset] = useState(0);

  useEffect(() => {
    setData(null);
    setError(null);
    setPricePageSize(DEFAULT_PRICE_PAGE_SIZE);
    setPriceOffset(0);
    getSecurity(ticker)
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }, [ticker]);

  // Independent of the company file fetch above — a new page or page size
  // only needs the one paged request, not the whole file reloaded.
  useEffect(() => {
    setPricePage(null);
    setPriceError(null);
    getSecurityPrices(ticker, pricePageSize, priceOffset)
      .then(setPricePage)
      .catch((e) => setPriceError(e instanceof ApiRequestError ? e.message : String(e)));
  }, [ticker, pricePageSize, priceOffset]);

  function changePricePageSize(size: number) {
    setPricePageSize(size);
    setPriceOffset(0); // a new page size starts back at the most recent page
  }

  function goToPreviousPricePage() {
    setPriceOffset((offset) => Math.max(0, offset - pricePageSize));
  }

  function goToNextPricePage() {
    setPriceOffset((offset) =>
      pricePage && offset + pricePageSize < pricePage.total ? offset + pricePageSize : offset,
    );
  }

  // Fetched independently of the company file itself (§15.1's per-section
  // degradation: a valuation failure shouldn't take the rest of the page
  // down with it, the same principle the /market endpoint already applies).
  useEffect(() => {
    setValuation(null);
    setValuationError(null);
    getValuation(ticker)
      .then(setValuation)
      .catch((e) => setValuationError(e instanceof ApiRequestError ? e.message : String(e)));
  }, [ticker]);

  // Same independent-fetch, per-section-degradation pattern as valuation
  // above — a slow or failed composite-score call never blocks the rest
  // of the page.
  useEffect(() => {
    setComposite(null);
    setCompositeError(null);
    getCompositeScore(ticker)
      .then(setComposite)
      .catch((e) => setCompositeError(e instanceof ApiRequestError ? e.message : String(e)));
  }, [ticker]);

  // §23's Bear/Base/Bull + tornado — cheap enough (a handful of DCF
  // re-runs) to fetch alongside the rest of the page. Monte Carlo is
  // deliberately NOT fetched here (10,000 real DCF re-runs) — see the
  // on-demand button in the Scenarios section below.
  useEffect(() => {
    setScenarios(null);
    setScenariosError(null);
    setTornado(null);
    setMonteCarlo(null);
    setMonteCarloError(null);
    getScenarios(ticker)
      .then(setScenarios)
      .catch((e) => setScenariosError(e instanceof ApiRequestError ? e.message : String(e)));
    getTornado(ticker).then(setTornado).catch(() => undefined); // tornado is a bonus chart, not worth its own error banner
  }, [ticker]);

  function runMonteCarlo() {
    setMonteCarloLoading(true);
    setMonteCarloError(null);
    getMonteCarlo(ticker)
      .then(setMonteCarlo)
      .catch((e) => setMonteCarloError(e instanceof ApiRequestError ? e.message : String(e)))
      .finally(() => setMonteCarloLoading(false));
  }

  if (error) {
    return (
      <div className="route stack">
        <button className="btn-link" onClick={onBack}>
          ← {backLabel}
        </button>
        <ErrorState
          whatFailed={`The file for ${ticker} could not be loaded`}
          whatItAffects="This company only."
          whatStillWorks="The company list and every other screen."
          whatHappensNext={<>Go back and try again, or reload. Underlying error: {error}</>}
        />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="route stack">
        <button className="btn-link" onClick={onBack}>
          ← {backLabel}
        </button>
        <SkeletonCard lines={3} />
      </div>
    );
  }

  const latest: PricePoint | null = data.price_history.at(-1) ?? null;

  // §14: "click any number → evidence panel". Wired here for the close
  // price, which is the one figure on this screen with a real derivation
  // chain today (raw feed → stored row → adjustment factor).
  function openCloseEvidence() {
    if (!latest || !data) return;
    setEvidence({
      title: `${data.ticker} — closing price`,
      whatItIs:
        "The last traded price of the session, as published by the Colombo Stock Exchange and stored in this system's own price table.",
      howItIsBuilt: (
        <p style={{ margin: 0 }}>
          Taken from the exchange's end-of-day trade summary and written unmodified. The adjusted
          price used by any model is this figure multiplied by the total-return adjustment factor,
          which accounts for dividends, bonus issues, splits and rights issues (Master Spec §7).
        </p>
      ),
      inputs: [
        { label: "Raw close", value: formatPrice(latest.close) },
        { label: "Open", value: formatPrice(latest.open) },
        { label: "High", value: formatPrice(latest.high) },
        { label: "Low", value: formatPrice(latest.low) },
        { label: "Adjustment factor", value: Number(latest.adj_factor).toFixed(6) },
        {
          label: "Adjusted close",
          value: formatPrice(String(Number(latest.close ?? 0) * Number(latest.adj_factor))),
        },
      ],
      howItCompares: (
        <p style={{ margin: 0 }}>
          Cross-sectional and own-history comparison arrives with the fundamental engine (Phase 2).
          This system currently stores {data.price_history.length} session
          {data.price_history.length === 1 ? "" : "s"} for this ticker
          {data.price_history.length < 60
            ? ", which is not yet enough history to compare against meaningfully."
            : " — enough depth for the comparison, once the engine that does it exists."}
        </p>
      ),
      source: { label: `cse.lk end-of-day trade summary, ${latest.date}` },
    });
  }

  return (
    <div className="route stack">
      <button className="btn-link" onClick={onBack}>
        ← {backLabel}
      </button>

      {data.quarantined && <QuarantineNotice ticker={data.ticker} />}

      <header className="card spread">
        <div>
          <span className="mono t-caption">{data.ticker}</span>
          <h1 style={{ marginTop: "var(--s1)" }}>{data.name}</h1>
        </div>
        <div style={{ textAlign: "right" }}>
          <span className="t-label">Last close</span>
          {latest?.close ? (
            <button
              className="hero-value"
              onClick={openCloseEvidence}
              style={{
                border: "none",
                background: "none",
                padding: 0,
                cursor: "pointer",
                display: "block",
                textDecoration: "underline",
                textDecorationStyle: "dotted",
                textUnderlineOffset: "4px",
                color: "var(--ink-1)",
              }}
              title="Show how this number is built"
            >
              {formatPrice(latest.close)}
            </button>
          ) : (
            <div className="hero-value unavailable">{UNAVAILABLE}</div>
          )}
          <span className="t-caption">LKR · {latest?.date ?? "no price stored"}</span>
        </div>
      </header>

      {data.sibling_tickers.length > 0 && (
        <div className="notice notice-neutral">
          <h3>
            {data.instrument_type === "non_voting"
              ? "This is the non-voting line of a company that also lists voting shares"
              : "This issuer has more than one listed line"}
          </h3>
          <p className="prose t-body">
            Also listed:{" "}
            {data.sibling_tickers.map((t, i) => (
              <span key={t}>
                {i > 0 && ", "}
                <button className="btn-link mono" onClick={() => onOpen(t)}>
                  {t}
                </button>
              </span>
            ))}
            . They are the same issuer, so they file one set of accounts — every fundamental and
            ratio on this page is shared with those lines, not computed separately. Prices,
            turnover and market capitalisation are not shared.
          </p>
        </div>
      )}

      <section className="card fact-grid" aria-label="Company facts">
        <Fact
          label="Instrument"
          value={data.instrument_type?.replace("_", "-") ?? null}
          note="The CSE lists lines, not companies. Only ordinary and non-voting lines are common equity a valuation model may be pointed at."
        />
        <Fact label="CSE sector" value={data.cse_sector} />
        <Fact
          label="Archetype"
          value={data.archetype}
          note="Drives the valuation model router (§15). Assigned by hand — GICS misclassifies several CSE conglomerates."
        />
        <Fact label="ISIN" value={data.isin} />
        <Fact label="Listing date" value={data.listing_date} />
        <Fact label="Fiscal year end" value={data.fiscal_year_end} />
        <Fact label="Turnover (latest)" value={latest ? formatMagnitude(latest.turnover) : null} />
        <Fact
          label="Shares issued"
          value={data.shares_issued === null ? null : formatMagnitude(data.shares_issued)}
          note={
            data.shares_issued_as_of
              ? `As at ${data.shares_issued_as_of}, from the CSE company summary.`
              : undefined
          }
        />
        <Fact
          label="Public free float"
          value={data.public_float_pct}
          note="Sourced from quarterly shareholding disclosures (§5), which are not ingested yet. Deliberately not derived from foreign holding — that is a different number, and Gate 2 treats this as 'cannot evaluate' rather than a pass."
        />
      </section>

      <section aria-labelledby="ladder-heading" className="stack-tight">
        <h2 id="ladder-heading">The price ladder (§26)</h2>
        {valuationError ? (
          <ErrorState
            whatFailed="The fair-value pipeline could not be loaded"
            whatItAffects="This section and the Fair value section below."
            whatStillWorks="Everything else on this page."
            whatHappensNext={<>Reload to try again. Underlying error: {valuationError}</>}
          />
        ) : !valuation ? (
          <SkeletonCard lines={2} />
        ) : valuation.price_ladder ? (
          <div className="card">
            <PriceLadder ladder={valuation.price_ladder} />
            {valuation.sanity && valuation.sanity.warned_by.length > 0 && (
              <p className="prose t-caption notice-caution" style={{ marginTop: "var(--s1)" }}>
                ⚠ {valuation.sanity.warn_reasons.join(" ")}
              </p>
            )}
          </div>
        ) : valuation.sanity && valuation.sanity.blocked ? (
          // TASK 0.1: a blended fair value existed but failed the
          // plausibility gate — a DIFFERENT, more specific reason than
          // "no anchors yet" below, and must say so rather than being
          // folded into the same generic notice.
          <div className="notice notice-caution">
            <h3>Fair value withheld — plausibility check failed</h3>
            <p className="prose t-body">
              A triangulated fair value was computed but did not pass TASK 0.1's plausibility gate,
              so it is not shown rather than risking a confident wrong answer (§1, law 4).
            </p>
            <ul className="prose t-body" style={{ marginTop: "var(--s1)" }}>
              {valuation.sanity.block_reasons.map((reason, i) => (
                <li key={i}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="notice notice-neutral">
            <h3>No price ladder yet</h3>
            <p className="prose t-body">
              Needs a triangulated fair value first — see the Fair value section below for what's
              missing. Never shown as a placeholder zero (§1, law 4).
            </p>
          </div>
        )}
      </section>

      {/* R1 T4.3.5 — "Make it the visual anchor of the page": moved up
          next to the price ladder, score-out-of-100 + VerdictPill up
          front, breakdown as a horizontal stacked bar rather than the
          fact-grid list alone (kept below for the per-pillar reasons a
          bar can't carry). */}
      <section aria-labelledby="composite-score-heading" className="stack-tight">
        <h2 id="composite-score-heading">Composite score (§38)</h2>
        {compositeError ? (
          <ErrorState
            whatFailed="The composite-score pipeline could not be loaded"
            whatItAffects="This section only."
            whatStillWorks="Everything else on this page."
            whatHappensNext={<>Reload to try again. Underlying error: {compositeError}</>}
          />
        ) : !composite ? (
          <SkeletonCard lines={2} />
        ) : (
          <div className="card stack-tight">
            <div style={{ display: "flex", alignItems: "baseline", gap: "var(--s3)", flexWrap: "wrap" }}>
              <div>
                <span className="t-label">Total score</span>
                <div className={composite.total_score !== null ? "hero-value" : "unavailable"} style={{ marginTop: "var(--s1)" }}>
                  {composite.total_score !== null ? `${Number(composite.total_score).toFixed(1)} / 100` : UNAVAILABLE}
                </div>
              </div>
              {composite.total_score !== null && (
                <VerdictPill
                  verdict={verdictFromPercentile(Number(composite.total_score))}
                  title="Banded from the same 70/40 thresholds every VerdictPill in this app uses."
                />
              )}
            </div>

            <CompositeScoreBar pillars={composite.pillars} />

            <p className="prose t-body">
              {composite.pillars.filter((p) => p.included).length} of 7 §38 pillars are blended into
              this score ({composite.pillars.filter((p) => p.included).map((p) => p.label).join(", ") || "none"}
              ). Valuation and Growth are always shown as evidence rather than ranked — a real,
              measured latency cost (ranking either needs a universe-wide pass), not a data gap — and
              any other pillar missing below is missing for this company's own data specifically. See
              each pillar's own reason.
            </p>

            <div className="fact-grid">
              {composite.pillars.map((p) => (
                <PillarFact key={p.key} pillar={p} />
              ))}
            </div>

            <p className="prose t-caption">
              Integrity veto (§11.1 Gate 3):{" "}
              {composite.integrity.vetoed
                ? `VETOED — ${composite.integrity.reason}`
                : composite.integrity.evaluable
                  ? "evaluated, no red flag found."
                  : composite.integrity.reason}
            </p>
          </div>
        )}
      </section>

      <section aria-labelledby="prices-heading" className="stack-tight">
        <h2 id="prices-heading">
          Price history{" "}
          <span className="t-caption">
            ({(pricePage?.total ?? data.price_history.length).toLocaleString("en-LK")} session
            {(pricePage?.total ?? data.price_history.length) === 1 ? "" : "s"} stored)
          </span>
        </h2>
        {data.price_history.length === 0 ? (
          <EmptyState title="No price rows stored for this ticker yet.">
            <p style={{ margin: 0 }}>
              The scheduled end-of-day capture runs automatically every trading day and will pick
              this up the next time this ticker trades.
            </p>
          </EmptyState>
        ) : (
          <>
            <PriceHistoryChart
              history={data.price_history}
              ceiling={valuation?.price_ladder ? Number(valuation.price_ladder.exit_threshold) : undefined}
              floor={
                valuation?.price_ladder ? Number(valuation.price_ladder.strong_accumulate_threshold) : undefined
              }
              average={
                // No portfolio-holding lookup wired into the company file yet
                // (a real, separate plumbing gap — see PriceHistoryChart's own
                // docstring) — the trailing mean of the SHOWN window, clearly
                // labelled as such rather than implying it's a cost basis.
                data.price_history.length > 0
                  ? data.price_history
                      .filter((p) => p.close !== null)
                      .reduce((sum, p, _i, arr) => sum + Number(p.close) / arr.length, 0)
                  : undefined
              }
              averageLabel="Trailing average"
            />
            {priceError ? (
              <ErrorState
                whatFailed="The price-history table could not be loaded"
                whatItAffects="This table only — the chart above uses a separate request."
                whatStillWorks="Everything else on this page."
                whatHappensNext={<>Reload to try again. Underlying error: {priceError}</>}
              />
            ) : !pricePage ? (
              <SkeletonCard lines={5} />
            ) : (
              <>
                <div className="table-wrap table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th scope="col">Date</th>
                        <th scope="col" className="right">Open</th>
                        <th scope="col" className="right">High</th>
                        <th scope="col" className="right">Low</th>
                        <th scope="col" className="right">Close</th>
                        <th scope="col" className="right">Volume</th>
                        <th scope="col" className="right">Adj. factor</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pricePage.items.map((p) => (
                        <tr key={p.date}>
                          <th scope="row" className="num" style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>
                            {p.date}
                          </th>
                          <td className="right num">{formatPrice(p.open)}</td>
                          <td className="right num">{formatPrice(p.high)}</td>
                          <td className="right num">{formatPrice(p.low)}</td>
                          <td className="right num">{formatPrice(p.close)}</td>
                          <td className="right num">
                            {p.volume === null ? (
                              <span className="unavailable">{UNAVAILABLE}</span>
                            ) : (
                              p.volume.toLocaleString("en-LK")
                            )}
                          </td>
                          <td className="right num">{Number(p.adj_factor).toFixed(6)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    flexWrap: "wrap",
                    gap: "var(--s3)",
                    marginTop: "var(--s3)",
                  }}
                >
                  <label className="t-caption" style={{ display: "flex", alignItems: "center", gap: "var(--s2)" }}>
                    Show
                    <select
                      value={pricePageSize}
                      onChange={(e) => changePricePageSize(Number(e.target.value))}
                      style={{ width: "auto" }}
                      aria-label="Sessions per page"
                    >
                      {PRICE_PAGE_SIZE_OPTIONS.map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </select>
                    per page
                  </label>

                  <div style={{ display: "flex", alignItems: "center", gap: "var(--s3)" }}>
                    <span className="t-caption num">
                      {pricePage.total === 0
                        ? "0 of 0"
                        : `${pricePage.offset + 1}–${pricePage.offset + pricePage.items.length} of ${pricePage.total}`}
                    </span>
                    <button onClick={goToPreviousPricePage} disabled={pricePage.offset === 0}>
                      ← Previous
                    </button>
                    <button
                      onClick={goToNextPricePage}
                      disabled={pricePage.offset + pricePage.items.length >= pricePage.total}
                    >
                      Next →
                    </button>
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="actions-heading" className="stack-tight">
        <h2 id="actions-heading">Corporate actions</h2>
        {data.corporate_actions.length === 0 ? (
          <EmptyState title="No corporate actions recorded for this company.">
            <p style={{ margin: 0 }}>
              {data.corporate_actions_last_scanned_at
                ? <>Announcements checked {formatAgo(data.corporate_actions_last_scanned_at)}, automatically —
                    nothing found yet for this company.</>
                : <>The daily automatic scan hasn't reached this company yet.</>}{" "}
              Nothing scraped ever affects a price until a human confirms it (§5).
            </p>
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Ex-date</th>
                  <th scope="col">Type</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.corporate_actions.map((a) => (
                  <tr key={a.id}>
                    <th scope="row" className="num" style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>
                      {a.ex_date}
                    </th>
                    <td>{ACTION_LABELS[a.type] ?? a.type}</td>
                    <td>
                      {a.confirmed ? (
                        <span className="status-tag status-confirmed">confirmed</span>
                      ) : a.rejected ? (
                        <span className="status-tag status-rejected">rejected</span>
                      ) : (
                        <span className="status-tag status-pending">awaiting review</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="ratios-heading" className="stack-tight">
        <h2 id="ratios-heading">Ratios</h2>
        <RatioCardGrid
          ratios={data.ratios}
          notComputable={data.ratios_not_yet_computable}
          periodEnd={data.ratio_period_end}
          trends={data.ratio_trends}
          percentiles={data.ratio_percentiles}
          series={data.ratio_series}
          onExplain={setEvidence}
        />
      </section>

      <section aria-labelledby="ke-heading" className="stack-tight">
        <h2 id="ke-heading">Cost of equity (§17)</h2>
        {data.cost_of_equity.ke === null ? (
          <div className="notice notice-neutral">
            <h3>Ke cannot be computed yet</h3>
            <p className="prose t-body">{data.cost_of_equity.note}</p>
          </div>
        ) : (
          <div className="card">
            <span className="t-label">Ke = Rf + β×ERP + size + illiquidity</span>
            <div className="hero-value">{(Number(data.cost_of_equity.ke) * 100).toFixed(2)}%</div>
            <PlainExplainer {...keExplainer(data.cost_of_equity)} />
            {data.cost_of_equity.is_lower_bound && (
              <p className="prose t-caption" style={{ marginTop: "var(--s2)" }}>
                {data.cost_of_equity.note}
              </p>
            )}
            <table className="data-table" style={{ marginTop: "var(--s4)" }}>
              <tbody>
                <tr>
                  <td style={{ color: "var(--ink-3)" }}>Risk-free rate (Rf, 364-day T-bill)</td>
                  <td className="right num">
                    {(Number(data.cost_of_equity.risk_free_rate) * 100).toFixed(2)}%
                  </td>
                </tr>
                <tr>
                  <td style={{ color: "var(--ink-3)" }}>Beta (Dimson-corrected, Blume-adjusted)</td>
                  <td className="right num">{Number(data.cost_of_equity.beta).toFixed(3)}</td>
                </tr>
                <tr>
                  <td style={{ color: "var(--ink-3)" }}>ERP effective (configured — PARAMETERS.md #10)</td>
                  <td className="right num">
                    {(Number(data.cost_of_equity.erp_effective) * 100).toFixed(2)}%
                  </td>
                </tr>
                <tr>
                  <td style={{ color: "var(--ink-3)" }}>β × ERP</td>
                  <td className="right num">
                    {(Number(data.cost_of_equity.beta_times_erp) * 100).toFixed(2)}%
                  </td>
                </tr>
                <tr>
                  <td style={{ color: "var(--ink-3)" }}>Size premium</td>
                  <td className="right num">
                    {data.cost_of_equity.size_premium === null ? (
                      <span className="unavailable">{UNAVAILABLE}</span>
                    ) : (
                      `${(Number(data.cost_of_equity.size_premium) * 100).toFixed(2)}%`
                    )}
                  </td>
                </tr>
                <tr>
                  <td style={{ color: "var(--ink-3)" }}>Illiquidity premium</td>
                  <td className="right num">
                    {data.cost_of_equity.illiquidity_premium === null ? (
                      <span className="unavailable">{UNAVAILABLE}</span>
                    ) : (
                      `${(Number(data.cost_of_equity.illiquidity_premium) * 100).toFixed(2)}%`
                    )}
                  </td>
                </tr>
                {data.cost_of_equity.implied_erp_cross_check !== null && (
                  <tr>
                    <td style={{ color: "var(--ink-3)" }}>
                      Implied ERP cross-check (§17.1, from the ASPI earnings-yield spread)
                    </td>
                    <td className="right num">
                      {(Number(data.cost_of_equity.implied_erp_cross_check) * 100).toFixed(2)}pp
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="routing-heading" className="stack-tight">
        <h2 id="routing-heading">Valuation routing</h2>
        <p className="prose t-body">
          §15/§16: which valuation methods apply to this company, and which are actively wrong for
          it. Not a valuation itself — it decides which of §18-26's methods apply; the fair value
          those methods produce, where it can be computed today, is below.
        </p>
        {data.valuation_routing.primary_models.length === 0 ? (
          <div className="notice notice-neutral">
            <h3>{data.archetype ? "No routing table entry" : "No archetype confirmed"}</h3>
            <p className="prose t-body">{data.valuation_routing.note}</p>
          </div>
        ) : (
          <div className="card">
            {!data.valuation_routing.in_published_table && (
              <p className="prose t-caption" style={{ marginBottom: "var(--s3)" }}>
                {data.valuation_routing.note}
              </p>
            )}
            {/* R1 T4.3.3 — one decision path, not three separate lists.
                The mockup's "Primary / Support" role split isn't real
                data this system's routing table carries (`primary_models`
                is a flat, unranked tuple — see `app.domain.
                valuation_router`) — the honest column this system can
                show is Used/Not used, which is what's genuinely decided
                per archetype, disclosed as such below rather than
                inventing a role split that would look more granular than
                the underlying decision actually is. */}
            <table className="data-table">
              <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3) 0 0" }}>
                This system doesn't yet rank "primary" vs "supporting" within the used set — every row
                below marked "Used" applies equally for this archetype.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col">Status</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                {data.valuation_routing.primary_models.map((m) => (
                  <tr key={m}>
                    <th scope="row" style={rowHeadStyle}>{m}</th>
                    <td>
                      <span className="chip" style={{ borderColor: "var(--pos-strong)", color: "var(--pos-strong)" }}>
                        ✓ Used
                      </span>
                    </td>
                    <td className="t-caption">{`Primary model for this company's archetype (§16).`}</td>
                  </tr>
                ))}
                {data.valuation_routing.suppressed.map((s) => (
                  <tr key={s.model}>
                    <th scope="row" style={rowHeadStyle}>{s.model}</th>
                    <td>
                      <span className="chip" style={{ borderColor: "var(--ink-4)", color: "var(--ink-4)" }}>
                        ✗ Not used
                      </span>
                    </td>
                    <td className="t-caption">{s.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.valuation_routing.meaningless_metrics.length > 0 && (
              <>
                <span className="t-label" style={{ marginTop: "var(--s4)", display: "block" }}>
                  Meaningless for this archetype
                </span>
                <ul className="not-built-list">
                  {data.valuation_routing.meaningless_metrics.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </>
            )}
            {data.valuation_routing.requires_earnings_normalisation && (
              <p className="prose t-caption" style={{ marginTop: "var(--s3)" }}>
                Cyclical or commodity-linked — earnings need normalising to a mid-cycle average
                before any multiple is applied (§15).
              </p>
            )}
          </div>
        )}
        <details>
          <summary className="t-caption" style={{ cursor: "pointer" }}>
            {data.valuation_routing.unanswered_questions.length} of §16's routing questions cannot
            be answered yet
          </summary>
          <ul className="not-built-list" style={{ marginTop: "var(--s2)" }}>
            {data.valuation_routing.unanswered_questions.map((q) => (
              <li key={q.question}>
                {q.question} — {q.missing_input}
              </li>
            ))}
          </ul>
        </details>
      </section>

      <section aria-labelledby="valuation-heading" className="stack-tight">
        <h2 id="valuation-heading">Fair value (§18-26)</h2>
        {valuationError ? (
          <ErrorState
            whatFailed="The fair-value pipeline could not be loaded"
            whatItAffects="This section only."
            whatStillWorks="Everything else on this page."
            whatHappensNext={<>Reload to try again. Underlying error: {valuationError}</>}
          />
        ) : !valuation ? (
          <SkeletonCard lines={2} />
        ) : (
          <div className="card stack-tight">
            <p className="prose t-body">{valuation.note}</p>

            <div className="fact-grid">
              <FairValueFact
                label="Justified P/B (§20.2)"
                value={valuation.justified_price_to_book_fair_value}
                warnings={valuation.justified_price_to_book_warnings}
              />
              <FairValueFact
                label="Residual income (§19.3)"
                value={valuation.residual_income_fair_value}
                warnings={valuation.residual_income_warnings}
              />
              <FairValueFact
                label="FCFF DCF (§18)"
                value={valuation.dcf.fair_value_per_share}
                warnings={valuation.dcf.warnings}
              />
              <FairValueFact
                label="Justified P/E (§20.2)"
                value={valuation.relative_valuation.fair_value_per_share_pe}
                warnings={valuation.relative_valuation.warnings}
              />
              <FairValueFact
                label="Justified P/S (§20.2)"
                value={valuation.relative_valuation.fair_value_per_share_ps}
                warnings={valuation.relative_valuation.warnings}
              />
              <FairValueFact
                label="Triangulated blend (§24)"
                value={valuation.triangulation.blended_fair_value_per_share}
                warnings={valuation.triangulation.warnings}
              />
            </div>

            {valuation.triangulation.dispersion_pct !== null && (
              <p className="prose t-caption">
                Dispersion across anchors: {(Number(valuation.triangulation.dispersion_pct) * 100).toFixed(1)}%
                {valuation.triangulation.missing_categories.length > 0 && (
                  <> — missing anchor categories: {valuation.triangulation.missing_categories.join(", ")}</>
                )}
              </p>
            )}

            <FairValueRange valuation={valuation} />

            <div>
              <span className="t-label">Margin of safety (§25)</span>
              <div className="hero-value">{(Number(valuation.margin_of_safety.total_pct) * 100).toFixed(0)}%</div>
              <p className="prose t-caption" style={{ marginTop: "var(--s1)" }}>
                {valuation.margin_of_safety.note}
              </p>
            </div>

            <p className="prose t-caption">The price ladder built from this fair value is shown above, near the top of the page.</p>
          </div>
        )}
      </section>

      <section aria-labelledby="scenarios-heading" className="stack-tight">
        <h2 id="scenarios-heading">Scenarios (§23)</h2>
        {scenariosError ? (
          <ErrorState
            whatFailed="Scenarios could not be loaded"
            whatItAffects="This section only."
            whatStillWorks="The Fair value section above."
            whatHappensNext={<>Reload to try again. Underlying error: {scenariosError}</>}
          />
        ) : !scenarios ? (
          <SkeletonCard lines={2} />
        ) : !scenarios.scenarios ? (
          <p className="prose t-caption">{scenarios.warnings[0] ?? "Not computable for this company yet."}</p>
        ) : (
          <div className="card stack-tight">
            <div className="fact-grid">
              <FairValueFact
                label="Bear"
                value={scenarios.scenarios.bear_value_per_share}
                warnings={[]}
              />
              <FairValueFact
                label="Base"
                value={scenarios.scenarios.base_value_per_share}
                warnings={[]}
              />
              <FairValueFact
                label="Bull"
                value={scenarios.scenarios.bull_value_per_share}
                warnings={[]}
              />
            </div>
            <p className="prose t-caption">{scenarios.scenarios.note}</p>
            {scenarios.distribution_note && (
              <p className="prose t-caption">{scenarios.distribution_note}</p>
            )}

            {tornado && tornado.bars.length > 0 && <TornadoChart tornado={tornado} />}

            <div>
              {!monteCarlo && !monteCarloLoading && (
                <button className="btn-primary" onClick={runMonteCarlo}>
                  Run Monte Carlo (10,000 draws)
                </button>
              )}
              {monteCarloLoading && <p className="prose t-caption">Running 10,000 draws…</p>}
              {monteCarloError && (
                <p className="prose t-caption" style={{ color: "var(--neg-strong)" }}>
                  {monteCarloError}
                </p>
              )}
              {monteCarlo && monteCarlo.p50 && (
                <div className="stack-tight" style={{ marginTop: "var(--s3)" }}>
                  <span className="t-label">Monte Carlo fair-value distribution</span>
                  <div className="fact-grid">
                    <FairValueFact label="P10" value={monteCarlo.p10} warnings={[]} />
                    <FairValueFact label="P50 (median)" value={monteCarlo.p50} warnings={[]} />
                    <FairValueFact label="P90" value={monteCarlo.p90} warnings={[]} />
                  </div>
                  {monteCarlo.probability_fair_value_exceeds_price && (
                    <p className="prose t-body">
                      P(fair value &gt; current price) ={" "}
                      {(Number(monteCarlo.probability_fair_value_exceeds_price) * 100).toFixed(0)}%
                    </p>
                  )}
                  <p className="prose t-caption">{monteCarlo.note}</p>
                </div>
              )}
              {monteCarlo && !monteCarlo.p50 && (
                <p className="prose t-caption">{monteCarlo.warnings[0] ?? "Not computable for this company yet."}</p>
              )}
            </div>
          </div>
        )}
      </section>

      {/* R1 T4.3.7 — was missing from this screen entirely (not a
          rendering fault: there was no code path for it at all), so this
          is a new section rather than a fix to an existing one. Built
          only from numbers already fetched on this page, templated into
          plain sentences — never a free-generated narrative (§5.0's own
          copy rule, same discipline `PlainExplainer` callers already
          follow elsewhere on this screen). The three-way T2.2
          classification applies: `null` here always means either "not
          enough real anchors yet" (missing input) or "price/valuation
          not yet loaded" (still fetching) — never a placeholder verdict. */}
      <section aria-labelledby="tells-you-heading" className="stack-tight">
        <h2 id="tells-you-heading">What this tells you</h2>
        {valuationError || compositeError ? (
          <ErrorState
            whatFailed="This summary needs both the fair-value and composite-score pipelines, and at least one failed"
            whatItAffects="This section only."
            whatStillWorks="The Fair value and Composite score sections above, independently."
            whatHappensNext={<>Reload to try again. Underlying error: {valuationError ?? compositeError}</>}
          />
        ) : !valuation || !composite ? (
          <SkeletonCard lines={3} />
        ) : (
          <WhatThisTellsYou data={data} valuation={valuation} composite={composite} latestClose={latest?.close ?? null} />
        )}
      </section>

      <section aria-labelledby="fundamentals-heading" className="stack-tight">
        <h2 id="fundamentals-heading">Financial statement lines</h2>
        <FundamentalsLinesTable
          ticker={data.ticker}
          fundamentals={data.fundamentals}
          onConfirmed={(updated) => {
            setData((prev) =>
              prev
                ? { ...prev, fundamentals: prev.fundamentals.map((f) => (f.id === updated.id ? updated : f)) }
                : prev,
            );
          }}
        />
      </section>

      <section className="notice notice-neutral" aria-labelledby="gaps-heading">
        <h3 id="gaps-heading">What this system cannot tell you yet</h3>
        <ul className="not-built-list">
          {data.not_yet_built.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="prose t-caption" style={{ marginTop: "var(--s3)" }}>
          Listed explicitly rather than shown as empty or zero — a confident-looking number that is
          actually a guess is the most dangerous object a financial interface can display (§1, law 4).
        </p>
      </section>

      {evidence && <EvidencePanel evidence={evidence} onClose={() => setEvidence(null)} />}
    </div>
  );
}

/** R1 T4.3.2 — real number, real driver, no verdict. The brief's own
 * dictated framing ("good sign to buy / not good sign") is explicitly
 * wrong for a discount rate — it is an input to the valuation below, not
 * a judgement about the stock, so this never says good/bad, only what
 * the number is, what it does, and why it landed where it did from its
 * own real components (never a peer-median comparison this system
 * doesn't compute). */
function keExplainer(ke: SecurityDetail["cost_of_equity"]) {
  const kePct = (Number(ke.ke) * 100).toFixed(1);
  const beta = ke.beta !== null ? Number(ke.beta) : null;
  const betaClause =
    beta === null
      ? ""
      : beta > 1.1
        ? ` — mainly because this stock's price moves more than the market (beta ${beta.toFixed(2)}).`
        : beta < 0.9
          ? ` — this stock's price moves less than the market (beta ${beta.toFixed(2)}), which pulls it down.`
          : ` — this stock's price moves roughly in line with the market (beta ${beta.toFixed(2)}).`;
  const extras: string[] = [];
  if (ke.size_premium !== null && Number(ke.size_premium) > 0) {
    extras.push(`a size premium of ${(Number(ke.size_premium) * 100).toFixed(1)}pp for being a smaller company`);
  }
  if (ke.illiquidity_premium !== null && Number(ke.illiquidity_premium) > 0) {
    extras.push(`an illiquidity premium of ${(Number(ke.illiquidity_premium) * 100).toFixed(1)}pp for how thinly it trades`);
  }
  const extrasClause = extras.length > 0 ? ` It also adds ${extras.join(" and ")}.` : "";

  return {
    headline: `Cost of equity ${kePct}%.`,
    body: (
      <>
        This is the annual return a shareholder should demand here, given Sri Lankan risk-free rates
        and this company's own share-price sensitivity. It is the discount rate used in the fair-value
        section below — a higher number produces a lower fair value, never the other way round{betaClause}
        {extrasClause} This system does not yet compute a CSE-wide median Ke to compare it against, so
        no such comparison is shown.
      </>
    ),
  };
}

function Fact({ label, value, note }: { label: string; value: string | null; note?: string }) {
  return (
    <div>
      <div className="t-label" title={note}>
        {label}
      </div>
      <div className={value ? "t-data" : "unavailable"} style={{ marginTop: "var(--s1)" }}>
        {value ?? UNAVAILABLE}
      </div>
    </div>
  );
}

/** One §18-26 anchor's fair value, or — far more often today — why it
 * isn't computable yet. Missing is displayed as missing, with the exact
 * reason named, never as a placeholder (§1, law 4). */
function FairValueFact({
  label,
  value,
  warnings,
}: {
  label: string;
  value: string | null;
  warnings: string[];
}) {
  return (
    <div>
      <div className="t-label">{label}</div>
      <div className={value ? "t-data" : "unavailable"} style={{ marginTop: "var(--s1)" }}>
        {value ? formatPrice(value) : UNAVAILABLE}
      </div>
      {!value && warnings.length > 0 && (
        <p className="prose t-caption" style={{ marginTop: "var(--s1)" }}>
          {warnings[0]}
        </p>
      )}
    </div>
  );
}

const TORNADO_ASSUMPTION_LABELS: Record<string, string> = {
  discount_rate: "Discount rate (WACC)",
  terminal_growth: "Terminal growth",
  revenue_growth_y1: "Revenue growth (Y1/Y2)",
  operating_margin_current: "Operating margin",
};

/** §23: "which single assumption moves the valuation most?" — one
 * horizontal bar per perturbed assumption, widest first (already sorted
 * server-side by `sensitivity_tornado`), width scaled to the widest bar
 * on the page so the visual comparison is meaningful across bars. */
function TornadoChart({ tornado }: { tornado: Tornado }) {
  const maxSpread = Math.max(...tornado.bars.map((b) => Number(b.spread)), 0.01);
  return (
    <div className="stack-tight">
      <span className="t-label">Sensitivity tornado — which assumption moves fair value most</span>
      {tornado.bars.map((bar) => {
        const pct = Math.min(100, (Number(bar.spread) / maxSpread) * 100);
        return (
          <div key={bar.assumption_name} style={{ display: "flex", alignItems: "center", gap: "var(--s2)" }}>
            <span className="t-caption" style={{ width: 170, flexShrink: 0 }}>
              {TORNADO_ASSUMPTION_LABELS[bar.assumption_name] ?? bar.assumption_name}
            </span>
            <div style={{ flex: 1, background: "var(--canvas-sunken)", borderRadius: 3, height: 10 }}>
              <div
                style={{
                  width: `${pct}%`,
                  background: "var(--brand-500)",
                  height: "100%",
                  borderRadius: 3,
                }}
              />
            </div>
            <span className="t-caption" style={{ width: 70, textAlign: "right", flexShrink: 0 }}>
              {formatPrice(bar.low_value_per_share)}–{formatPrice(bar.high_value_per_share)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** R1 T4.3.4: a real fair-value RANGE rather than a single point estimate
 * — the low/high spread across whichever §18-26 anchors actually computed
 * for this company (never a fabricated §23 bear/bull scenario; this
 * project's own bear/bull DCF scenarios need multi-year growth/margin
 * history most companies don't have yet — see `app.domain.scenarios`'s
 * own module docstring). "Bear"/"Bull" here means "the lowest/highest of
 * the real anchors that actually computed," not a stress test. With a
 * single anchor there's no real spread — shown as one number, not a fake
 * range with identical ends. */
/** R1 T4.3.7 — a real, templated synthesis of what's already on this
 * page, not a new inference. Every clause below is either a direct
 * readout of an already-fetched number or a named absence of one; it
 * never invents a qualitative judgement (a "bull case" bullet, a
 * falsification condition) this system hasn't actually computed. */
function WhatThisTellsYou({
  data,
  valuation,
  composite,
  latestClose,
}: {
  data: SecurityDetail;
  valuation: CompanyValuation;
  composite: CompositeScore;
  latestClose: string | null;
}) {
  const base = valuation.triangulation.blended_fair_value_per_share
    ? Number(valuation.triangulation.blended_fair_value_per_share)
    : null;
  const price = latestClose !== null ? Number(latestClose) : null;
  const zone = valuation.price_ladder?.current_zone ?? null;

  const positionSentence =
    base !== null && price !== null ? (
      <>
        At {formatPrice(String(price))}, {data.ticker} trades{" "}
        {price < base ? "below" : price > base ? "above" : "at"} this system's own base-case fair
        value of {formatPrice(String(base))}
        {zone ? <> — the price ladder currently places it in the "{zone.replace(/_/g, " ")}" zone.</> : "."}
      </>
    ) : (
      <>
        No base-case fair value is computable for {data.ticker} yet — see the Fair value section
        above for exactly which anchor category is missing.
      </>
    );

  const strongPillars = composite.pillars.filter((p) => p.included && p.score !== null && Number(p.score) >= 70);
  const weakPillars = composite.pillars.filter((p) => p.included && p.score !== null && Number(p.score) < 40);
  const scoreSentence =
    composite.total_score !== null ? (
      <>
        The composite score is {Number(composite.total_score).toFixed(0)}/100
        {strongPillars.length > 0 && (
          <>, driven up by {strongPillars.map((p) => p.label.toLowerCase()).join(" and ")}</>
        )}
        {weakPillars.length > 0 && (
          <>{strongPillars.length > 0 ? ", and" : ","} held back by {weakPillars.map((p) => p.label.toLowerCase()).join(" and ")}</>
        )}
        {composite.integrity.vetoed && <> — though the integrity gate has vetoed it (see below).</>}.
      </>
    ) : (
      <>No composite score is computable for {data.ticker} yet — {composite.pillars.filter((p) => p.included).length} of 7 pillars are usable, below the minimum this system requires to publish one.</>
    );

  return (
    <div className="card stack-tight">
      <p className="prose t-body">{positionSentence}</p>
      <p className="prose t-body">{scoreSentence}</p>
      <p className="prose t-caption">
        This is a readout of numbers already computed elsewhere on this page, not a new judgement —
        a qualitative bull/bear case and named falsification conditions (the UI spec's own "case in
        five lines" and "what would change this") would need investment reasoning this system does
        not generate; showing a machine-written version of that would be exactly the "confident,
        precise, fictional" text this project's own copy rules forbid (§1, law 4; §5.0). A human
        reviewer's own thesis for a held position belongs in the Journal screen's decision record
        instead (§37).
      </p>
    </div>
  );
}

function FairValueRange({ valuation }: { valuation: CompanyValuation }) {
  const anchors = [
    valuation.justified_price_to_book_fair_value,
    valuation.residual_income_fair_value,
    valuation.dcf.fair_value_per_share,
  ]
    .filter((v): v is string => v !== null)
    .map(Number);
  if (anchors.length === 0) return null;

  const bear = Math.min(...anchors);
  const bull = Math.max(...anchors);
  const base = valuation.triangulation.blended_fair_value_per_share
    ? Number(valuation.triangulation.blended_fair_value_per_share)
    : anchors.reduce((a, b) => a + b, 0) / anchors.length;

  if (anchors.length === 1) {
    return (
      <p className="prose t-caption">
        Only one real anchor computed for this company — no genuine range to show yet (not the
        same as a wide one; see "missing anchor categories" above for why).
      </p>
    );
  }

  return (
    <div>
      <span className="t-label">Fair value range — low to high across real anchors</span>
      <p className="prose t-body" style={{ marginTop: "var(--s1)" }}>
        Bear {formatPrice(String(bear))} · Base {formatPrice(String(base))} · Bull{" "}
        {formatPrice(String(bull))}
      </p>
    </div>
  );
}

/** One §38 pillar's 0-100 score, or — for Valuation/Growth always, and
 * for any other pillar this specific company lacks the data for — the
 * exact reason it's excluded rather than a placeholder number. */
/** R1 T4.3.5's own horizontal-stacked-bar breakdown. Segment WIDTH is
 * each included pillar's real §38 weight (so Business quality's 25%
 * segment is visibly bigger than Risk's 5%); segment FILL is that
 * pillar's own score, banded from the calm palette by the same 70/40
 * thresholds `VerdictPill` uses everywhere else — never a red-to-green
 * ramp (§1 law 6). A pillar with `included: false` gets a hatched,
 * `--ink-4` segment rather than being silently dropped from the bar,
 * so an excluded pillar still occupies its real share of the 100%
 * width instead of making the included pillars look like the whole
 * picture. */
function CompositeScoreBar({ pillars }: { pillars: PillarScore[] }) {
  const totalWeight = pillars.reduce((sum, p) => sum + Number(p.weight_pct), 0) || 1;
  return (
    <div>
      <div
        style={{
          display: "flex",
          width: "100%",
          height: 14,
          borderRadius: 4,
          overflow: "hidden",
          border: "1px solid var(--border)",
        }}
      >
        {pillars.map((p) => {
          const widthPct = (Number(p.weight_pct) / totalWeight) * 100;
          const score = p.included && p.score !== null ? Number(p.score) : null;
          const band = score !== null ? verdictFromPercentile(score) : "no_data";
          const fill =
            band === "strong"
              ? "var(--pos-strong)"
              : band === "adequate"
                ? "var(--brand-300)"
                : band === "weak"
                  ? "var(--caution)"
                  : "var(--ink-4)";
          return (
            <a
              key={p.key}
              href={`#pillar-${p.key}`}
              title={`${p.label}: ${score !== null ? `${score.toFixed(1)}/100` : p.reason ?? "no score"} (weight ${Number(p.weight_pct).toFixed(0)}%)`}
              style={{
                width: `${widthPct}%`,
                background: fill,
                opacity: p.included ? 1 : 0.35,
                borderRight: "1px solid var(--bg)",
              }}
            />
          );
        })}
      </div>
      <div className="t-caption muted" style={{ marginTop: "var(--s1)" }}>
        Segment width = §38 weight, fill = score band. Hover a segment for its number; faded segments
        aren't included in the total. Click any pillar card below for its own evidence.
      </div>
    </div>
  );
}

function PillarFact({ pillar }: { pillar: PillarScore }) {
  return (
    <div id={`pillar-${pillar.key}`}>
      <div className="t-label">
        {pillar.label} ({Number(pillar.weight_pct).toFixed(0)}%)
      </div>
      <div className={pillar.included ? "t-data" : "unavailable"} style={{ marginTop: "var(--s1)" }}>
        {pillar.included && pillar.score !== null ? Number(pillar.score).toFixed(1) : UNAVAILABLE}
      </div>
      {!pillar.included && pillar.reason && (
        <p className="prose t-caption" style={{ marginTop: "var(--s1)" }}>
          {pillar.reason}
        </p>
      )}
    </div>
  );
}
