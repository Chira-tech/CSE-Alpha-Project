import { useEffect, useState } from "react";
import { ApiRequestError, getSectorDrilldown } from "../api";
import { Delta } from "./Delta";
import { ErrorState, SkeletonCard } from "./states";
import { Treemap } from "./Treemap";
import { formatMagnitude, UNAVAILABLE } from "../format";
import type { SectorCompany, SectorDrilldown, SectorSensitivityRow } from "../types";

/**
 * R1 T4.6.4 — "the highest-value new feature in this release." Opens
 * from a sector click on the sensitivity matrix, carrying that row's
 * own already-fetched macro sensitivities through (§3 of the brief's
 * own drill-down spec) rather than re-fetching them.
 */
export function SectorDrilldownPanel({
  sector,
  sensitivityRow,
  onClose,
  onOpenCompany,
}: {
  sector: string;
  sensitivityRow: SectorSensitivityRow | undefined;
  onClose: () => void;
  onOpenCompany: (ticker: string) => void;
}) {
  const [data, setData] = useState<SectorDrilldown | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    getSectorDrilldown(sector)
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }, [sector]);

  return (
    <div
      role="dialog"
      aria-labelledby="drilldown-heading"
      style={{
        position: "fixed",
        inset: 0,
        background: "color-mix(in srgb, var(--bg) 60%, transparent)",
        display: "flex",
        justifyContent: "flex-end",
        zIndex: 50,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ width: "min(760px, 100%)", height: "100%", overflowY: "auto", borderRadius: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h2 id="drilldown-heading">{sector}</h2>
          <button className="btn-link" onClick={onClose}>Close ✕</button>
        </div>

        {error ? (
          <ErrorState
            whatFailed={`The ${sector} sector drill-down could not be loaded`}
            whatItAffects="This panel only."
            whatStillWorks="The sensitivity matrix and the rest of the Macro screen behind it."
            whatHappensNext={`Reload to try again. Underlying error: ${error}`}
          />
        ) : !data ? (
          <>
            <p className="prose t-caption" style={{ marginTop: "var(--s3)" }}>
              Computing real fair-value gaps for every confirmed ticker (a genuine ~15-20s pass — see
              this panel's own note below once loaded)…
            </p>
            <SkeletonCard lines={6} />
          </>
        ) : (
          <div className="stack-tight" style={{ marginTop: "var(--s3)" }}>
            <section aria-labelledby="treemap-heading" className="stack-tight">
              <h3 id="treemap-heading">Market share by market cap</h3>
              {data.excluded_from_market_cap_pct > 0 && (
                <p className="prose t-caption">
                  {data.excluded_from_market_cap_pct} constituent
                  {data.excluded_from_market_cap_pct === 1 ? "" : "s"} excluded from this treemap and
                  from every % of sector below — missing real shares-issued or a real recent close,
                  not treated as zero.
                </p>
              )}
              <Treemap
                items={data.companies
                  .filter((c) => c.market_cap !== null)
                  .map((c) => ({ key: c.ticker, label: c.ticker, value: Number(c.market_cap) }))}
                formatValue={(v) => formatMagnitude(String(v))}
                onSelect={onOpenCompany}
              />
            </section>

            <section aria-labelledby="ranked-heading" className="stack-tight">
              <h3 id="ranked-heading">Constituents, ranked by market cap</h3>
              <p className="prose t-caption">{data.composite_score_omitted_reason}</p>
              <div className="table-wrap table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Ticker</th>
                      <th scope="col" className="right">Market cap</th>
                      <th scope="col" className="right">% of sector</th>
                      <th scope="col" className="right">Fair value gap</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.companies.map((c) => (
                      <CompanyRow key={c.ticker} c={c} onOpen={onOpenCompany} />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section aria-labelledby="sensitivities-heading" className="stack-tight">
              <h3 id="sensitivities-heading">Macro sensitivities (§33)</h3>
              {!sensitivityRow || sensitivityRow.estimates.length === 0 ? (
                <p className="prose t-caption muted">
                  No cell in the sensitivity matrix above has enough real history to estimate for this
                  sector yet.
                </p>
              ) : (
                <ul className="not-built-list">
                  {sensitivityRow.estimates.map((e) => (
                    <li key={e.shock_name}>
                      {e.shock_name}:{" "}
                      {e.significant
                        ? `${e.direction_label} (coefficient ${Number(e.coefficient).toFixed(4)}, p=${Number(e.p_value).toFixed(3)}, n=${e.observation_count})`
                        : `not significant (n=${e.observation_count})`}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function CompanyRow({ c, onOpen }: { c: SectorCompany; onOpen: (ticker: string) => void }) {
  return (
    <tr>
      <th scope="row" style={rowHeadStyle}>
        <button className="btn-link mono" onClick={() => onOpen(c.ticker)}>
          {c.ticker}
        </button>
      </th>
      <td className="right num" title={c.market_cap === null ? (c.market_cap_reason ?? undefined) : undefined}>
        {c.market_cap !== null ? formatMagnitude(c.market_cap) : UNAVAILABLE}
      </td>
      <td className="right num">
        {c.pct_of_sector !== null ? `${(Number(c.pct_of_sector) * 100).toFixed(1)}%` : UNAVAILABLE}
      </td>
      <td className="right" title={c.fair_value_gap_pct === null ? (c.gap_reason ?? undefined) : undefined}>
        {c.fair_value_gap_pct !== null ? (
          <Delta percentage={Number(c.fair_value_gap_pct) * 100} />
        ) : (
          <span className="muted">{UNAVAILABLE}</span>
        )}
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
