import { useEffect, useState } from "react";
import { ApiRequestError, getSecurity } from "../api";
import { EvidencePanel, type Evidence } from "../components/EvidencePanel";
import { ProvenanceChip } from "../components/ProvenanceChip";
import { RatioTable } from "../components/RatioTable";
import { EmptyState, ErrorState, QuarantineNotice, SkeletonCard } from "../components/states";
import { formatMagnitude, formatPrice, UNAVAILABLE } from "../format";
import type { PricePoint, SecurityDetail } from "../types";

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

  useEffect(() => {
    setData(null);
    setError(null);
    getSecurity(ticker)
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
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
            ({data.price_history.length} session{data.price_history.length === 1 ? "" : "s"} stored)
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
                {[...data.price_history].reverse().map((p) => (
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
          onExplain={setEvidence}
        />
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
