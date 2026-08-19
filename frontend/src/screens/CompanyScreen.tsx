import { useEffect, useState } from "react";
import { ApiRequestError, getSecurity, getSecurityPrices, getValuation } from "../api";
import { EvidencePanel, type Evidence } from "../components/EvidencePanel";
import { PriceHistoryChart } from "../components/PriceHistoryChart";
import { PriceLadder } from "../components/PriceLadder";
import { ProvenanceChip } from "../components/ProvenanceChip";
import { RatioTable } from "../components/RatioTable";
import { EmptyState, ErrorState, QuarantineNotice, SkeletonCard } from "../components/states";
import { formatMagnitude, formatPrice, UNAVAILABLE } from "../format";
import type { CompanyValuation, PriceHistoryPage, PricePoint, SecurityDetail } from "../types";

/** The price-history table is paged server-side (`GET
 * /securities/{ticker}/prices`, SQL limit/offset) rather than loading a
 * year-plus of daily rows and slicing client-side — a company with a
 * year of daily rows would otherwise make this the single largest
 * response on the page for a table showing five rows at a time. */
const PRICE_PAGE_SIZE_OPTIONS = [5, 10, 25, 50] as const;
const DEFAULT_PRICE_PAGE_SIZE = 5;

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
}: {
  ticker: string;
  onBack: () => void;
  /** Jump to another line of the same issuer. */
  onOpen: (ticker: string) => void;
}) {
  const [data, setData] = useState<SecurityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [valuation, setValuation] = useState<CompanyValuation | null>(null);
  const [valuationError, setValuationError] = useState<string | null>(null);
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

  if (error) {
    return (
      <div className="route stack">
        <button className="btn-link" onClick={onBack}>
          ← All companies
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
          ← All companies
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
        ← All companies
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

      <section aria-labelledby="prices-heading" className="stack-tight">
        <h2 id="prices-heading">
          Price history{" "}
          <span className="t-caption">
            ({(pricePage?.total ?? data.price_history.length).toLocaleString("en-LK")} session
            {(pricePage?.total ?? data.price_history.length) === 1 ? "" : "s"} stored)
          </span>
        </h2>
        {data.price_history.length === 0 ? (
          <EmptyState title="No price rows stored for this ticker.">
            <p style={{ margin: 0 }}>
              Run <span className="code-hint">python -m app.cli bootstrap</span> to load the latest
              session, or wait for the scheduled end-of-day job.
            </p>
          </EmptyState>
        ) : (
          <>
            <PriceHistoryChart history={data.price_history} />
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
          <EmptyState title="No corporate actions recorded.">
            <p style={{ margin: 0 }}>
              Run <span className="code-hint">python -m app.cli ingest-corporate-actions</span> to
              scrape announcements into the confirm queue. Nothing scraped affects a price until a
              human confirms it (§5).
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
        <RatioTable
          ratios={data.ratios}
          notComputable={data.ratios_not_yet_computable}
          periodEnd={data.ratio_period_end}
          trends={data.ratio_trends}
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
            <span className="t-label">Primary models</span>
            <ul className="not-built-list">
              {data.valuation_routing.primary_models.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
            {data.valuation_routing.suppressed.length > 0 && (
              <>
                <span className="t-label">Suppressed, and why</span>
                <ul className="not-built-list">
                  {data.valuation_routing.suppressed.map((s) => (
                    <li key={s.model}>
                      <strong>{s.model}</strong> — {s.reason}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {data.valuation_routing.meaningless_metrics.length > 0 && (
              <>
                <span className="t-label">Meaningless for this archetype</span>
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

            <div>
              <span className="t-label">Margin of safety (§25)</span>
              <div className="hero-value">{(Number(valuation.margin_of_safety.total_pct) * 100).toFixed(0)}%</div>
              <p className="prose t-caption" style={{ marginTop: "var(--s1)" }}>
                {valuation.margin_of_safety.note}
              </p>
            </div>

            {valuation.price_ladder ? (
              <div>
                <span className="t-label">The price ladder (§26)</span>
                <div style={{ marginTop: "var(--s2)" }}>
                  <PriceLadder ladder={valuation.price_ladder} />
                </div>
                {valuation.sanity && valuation.sanity.warned_by.length > 0 && (
                  <p className="prose t-caption notice-caution" style={{ marginTop: "var(--s1)" }}>
                    ⚠ {valuation.sanity.warn_reasons.join(" ")}
                  </p>
                )}
              </div>
            ) : valuation.sanity && valuation.sanity.blocked ? (
              // TASK 0.1: a blended fair value existed but failed the
              // plausibility gate — a DIFFERENT, more specific reason
              // than "no anchors yet" below, and must say so rather than
              // being folded into the same generic notice.
              <div className="notice notice-caution">
                <h3>Fair value withheld — plausibility check failed</h3>
                <p className="prose t-body">
                  A triangulated fair value was computed but did not pass TASK 0.1's plausibility
                  gate, so it is not shown rather than risking a confident wrong answer (§1, law 4).
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
                  Needs a triangulated fair value first — see the gaps named above. Never shown as a
                  placeholder zero (§1, law 4).
                </p>
              </div>
            )}
          </div>
        )}
      </section>

      <section aria-labelledby="fundamentals-heading" className="stack-tight">
        <h2 id="fundamentals-heading">Financial statement lines</h2>
        {data.fundamentals.length === 0 ? (
          <EmptyState title="No statement lines extracted.">
            <p style={{ margin: 0 }}>
              The financial-statement scan reads filed PDFs into this table. Extracted figures are
              marked AI-assisted and cannot enter any valuation until confirmed (§8).
            </p>
          </EmptyState>
        ) : (
          <div className="table-wrap table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Period end</th>
                  <th scope="col">Type</th>
                  <th scope="col">Line</th>
                  <th scope="col" className="right">Value (LKR '000)</th>
                  <th scope="col">Provenance</th>
                </tr>
              </thead>
              <tbody>
                {data.fundamentals.map((f) => (
                  <tr key={f.id}>
                    <th scope="row" className="num" style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>
                      {f.period_end}
                    </th>
                    <td>{f.period_type}</td>
                    <td className="mono">{f.statement_line}</td>
                    <td className="right num">{formatPrice(f.value)}</td>
                    <td>
                      <ProvenanceChip tier={f.provenance_tier} />
                      {!f.confirmed && f.provenance_tier === "A" && (
                        <>
                          {" "}
                          <span className="status-tag status-pending">awaiting review</span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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
