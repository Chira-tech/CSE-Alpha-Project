import { useEffect, useState } from "react";
import { ApiRequestError, getSecurity } from "../api";
import { ProvenanceChip } from "../components/ProvenanceChip";
import { formatMagnitude, formatPrice, UNAVAILABLE } from "../format";
import type { SecurityDetail } from "../types";

const ACTION_LABELS: Record<string, string> = {
  dividend_cash: "Cash dividend",
  bonus_issue: "Bonus issue",
  rights_issue: "Rights issue",
  stock_split: "Stock split",
  consolidation: "Consolidation",
  delisting: "Delisting",
  suspension: "Suspension",
};

export function CompanyScreen({ ticker, onBack }: { ticker: string; onBack: () => void }) {
  const [data, setData] = useState<SecurityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    getSecurity(ticker)
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : "Failed to load"));
  }, [ticker]);

  if (error) return <p className="error-text">Couldn't load {ticker}: {error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  const latest = data.price_history.at(-1) ?? null;

  return (
    <div className="stack">
      <button type="button" className="btn-link" onClick={onBack}>
        ← back to companies
      </button>

      {data.quarantined && (
        <div className="quarantine-notice">
          This ticker is quarantined by an unresolved data-quality alert. Master Spec §7 requires it
          be excluded from every model until a human resolves the underlying issue.
        </div>
      )}

      <header className="company-header">
        <div>
          <div className="mono company-ticker">{data.ticker}</div>
          <h2 className="company-name">{data.name}</h2>
        </div>
        <div className="company-price">
          <div className="hero-value num">{formatPrice(latest?.close ?? null)}</div>
          <div className="muted">LKR · close {latest?.date ?? UNAVAILABLE}</div>
        </div>
      </header>

      <section className="facts-grid">
        <Fact label="CSE sector" value={data.cse_sector} />
        <Fact label="Archetype" value={data.archetype} hint="Drives the valuation model router (§15). Assigned by hand — GICS misclassifies several CSE conglomerates." />
        <Fact label="ISIN" value={data.isin} />
        <Fact label="Listing date" value={data.listing_date} />
        <Fact label="Fiscal year end" value={data.fiscal_year_end} />
        <Fact
          label="Turnover (latest)"
          value={latest ? formatMagnitude(latest.turnover) : null}
        />
      </section>

      <section>
        <h3>Price history ({data.price_history.length} session{data.price_history.length === 1 ? "" : "s"} stored)</h3>
        {data.price_history.length === 0 ? (
          <p className="muted">No price rows stored yet for this ticker.</p>
        ) : (
          <table className="queue-table">
            <thead>
              <tr>
                <th>Date</th>
                <th className="right">Open</th>
                <th className="right">High</th>
                <th className="right">Low</th>
                <th className="right">Close</th>
                <th className="right">Volume</th>
                <th className="right">Adj. factor</th>
              </tr>
            </thead>
            <tbody>
              {[...data.price_history].reverse().map((p) => (
                <tr key={p.date}>
                  <td className="num">{p.date}</td>
                  <td className="right num">{formatPrice(p.open)}</td>
                  <td className="right num">{formatPrice(p.high)}</td>
                  <td className="right num">{formatPrice(p.low)}</td>
                  <td className="right num">{formatPrice(p.close)}</td>
                  <td className="right num">
                    {p.volume === null ? UNAVAILABLE : p.volume.toLocaleString("en-LK")}
                  </td>
                  <td className="right num">{Number(p.adj_factor).toFixed(6)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h3>Corporate actions</h3>
        {data.corporate_actions.length === 0 ? (
          <p className="muted">
            None recorded. Run the corporate-actions scan to populate the confirm queue.
          </p>
        ) : (
          <table className="queue-table">
            <thead>
              <tr>
                <th>Ex-date</th>
                <th>Type</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.corporate_actions.map((a) => (
                <tr key={a.id}>
                  <td className="num">{a.ex_date}</td>
                  <td>{ACTION_LABELS[a.type] ?? a.type}</td>
                  <td>
                    {a.confirmed ? (
                      <span className="status-confirmed">confirmed</span>
                    ) : a.rejected ? (
                      <span className="status-rejected">rejected</span>
                    ) : (
                      <span className="status-pending">awaiting review</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h3>Financial statement lines</h3>
        {data.fundamentals.length === 0 ? (
          <p className="muted">
            None extracted yet. The financial-statement scan populates these from filed PDFs.
          </p>
        ) : (
          <table className="queue-table">
            <thead>
              <tr>
                <th>Period end</th>
                <th>Type</th>
                <th>Line</th>
                <th className="right">Value (LKR '000)</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {data.fundamentals.map((f) => (
                <tr key={f.id}>
                  <td className="num">{f.period_end}</td>
                  <td>{f.period_type}</td>
                  <td className="mono">{f.statement_line}</td>
                  <td className="right num">{formatPrice(f.value)}</td>
                  <td>
                    <ProvenanceChip tier={f.provenance_tier} />
                    {!f.confirmed && f.provenance_tier === "A" && (
                      <span className="status-pending"> awaiting review</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="not-built">
        <h3>What this system cannot tell you yet</h3>
        <ul>
          {data.not_yet_built.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="muted">
          Listed explicitly rather than shown as empty or zero — a confident-looking number that is
          actually a guess is the most dangerous thing a financial interface can display.
        </p>
      </section>
    </div>
  );
}

function Fact({ label, value, hint }: { label: string; value: string | null; hint?: string }) {
  return (
    <div className="fact">
      <div className="field-label" title={hint}>
        {label}
      </div>
      <div className={value ? "" : "muted"}>{value ?? UNAVAILABLE}</div>
    </div>
  );
}
