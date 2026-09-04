import type { SectorSensitivity, SectorSensitivityRow, SensitivityEstimate } from "../types";

/**
 * §33's sector sensitivity matrix: each cell is a real OLS regression of
 * one sector's equal-weighted daily return on one real macro shock
 * series — never a hard-coded relationship (§33's own explicit warning
 * against illustrative numbers presented as estimates). See
 * `app.domain.sector_sensitivity`'s own module docstring on the backend
 * for exactly which shocks are real and why §33's own illustrative Oil/
 * Tourism/Fiscal columns aren't among them.
 *
 * MOST CELLS READ "—" TODAY, AND THAT IS HONEST, NOT BROKEN: a cell
 * needs at least 20 real overlapping trading-day observations between a
 * sector's return series and the shock series, and this system's real
 * CBSL series only go back a handful of days so far (see Data health).
 * A dash here means "not enough real history yet", never "no
 * relationship" and never a fabricated placeholder number — exactly the
 * anti-pattern §17 forbids.
 */
export function SectorSensitivityMatrix({
  data,
  onSelectSector,
}: {
  data: SectorSensitivity;
  /** R1 T4.6.4 — clicking a sector name opens its drill-down panel
   * (market-share treemap, ranked constituents, this row's own
   * sensitivities carried through). Optional so this component still
   * works standalone wherever it's used without a drill-down host. */
  onSelectSector?: (sector: string) => void;
}) {
  const rows = [...data.rows].sort((a, b) => b.constituent_count - a.constituent_count);
  const cellCount = rows.reduce((n, r) => n + r.estimates.length, 0);
  // R1 T4.6.2 — "sequential muted scale... cell = sensitivity direction
  // and magnitude." Normalised against the largest real |coefficient|
  // anywhere in THIS matrix (not a fixed constant, which would misread
  // as soon as the real distribution shifted) so shading is relative to
  // what this system has actually estimated today.
  const maxAbsCoeff = Math.max(
    0,
    ...rows.flatMap((r) => r.estimates.filter((e) => e.significant).map((e) => Math.abs(Number(e.coefficient)))),
  );

  return (
    <div className="stack-tight">
      <div className="notice notice-neutral">
        <h3>{cellCount === 0 ? "No cell has enough real history to estimate from yet" : "Read this matrix carefully"}</h3>
        <p className="prose t-caption" style={{ margin: 0 }}>
          Colored = significant (p&lt;0.05). Filled dot = tested, not significant. Outline-only dot =
          not yet enough history to test. A row muted below is excluded — too few real constituents.
        </p>
        <details style={{ marginTop: "var(--s2)" }}>
          <summary className="t-caption" style={{ cursor: "pointer" }}>
            Full explanation
          </summary>
          <p className="prose t-body" style={{ marginTop: "var(--s2)" }}>
            Each cell is a real regression of a sector's own daily return series on a real macro shock
            series — coefficient, p-value and observation count all computed live, never illustrative.
            A cell needs at least 20 real overlapping trading-day observations to produce an estimate
            at all; below that it shows a hollow dot, not a guessed number. Only "significant" cells (p
            &lt; 0.05) carry a direction — the rest are shown as not significant rather than silently
            omitted, so a thin real history doesn't masquerade as "no relationship".
          </p>
          {data.warnings.map((w) => (
            <p key={w} className="prose t-caption" style={{ marginTop: "var(--s2)" }}>
              {w}
            </p>
          ))}
        </details>
      </div>

      <div className="table-wrap table-scroll">
        <table className="data-table">
          <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
            As of {data.as_of}. Sector return series are equal-weighted across each sector's real
            constituents.
          </caption>
          <thead>
            <tr>
              <th scope="col">Sector</th>
              <th scope="col" className="right">Names</th>
              {data.shocks_used.map((s) => (
                <th key={s} scope="col" className="right">
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <SensitivityRow
                key={row.sector}
                row={row}
                shocks={data.shocks_used}
                maxAbsCoeff={maxAbsCoeff}
                onSelectSector={onSelectSector}
              />
            ))}
          </tbody>
        </table>
      </div>

      {data.thin_sectors.length > 0 && (
        <details className="card-sunken">
          <summary className="t-data" style={{ cursor: "pointer" }}>
            {data.thin_sectors.length} sector{data.thin_sectors.length === 1 ? "" : "s"} excluded
            entirely — too few real constituents to build a return series from
          </summary>
          <table className="data-table" style={{ marginTop: "var(--s3)" }}>
            <thead>
              <tr>
                <th scope="col">Sector</th>
                <th scope="col" className="right">Real constituents</th>
              </tr>
            </thead>
            <tbody>
              {data.thin_sectors.map(([sector, count]) => (
                <tr key={sector}>
                  <th scope="row" style={rowHeadStyle}>{sector}</th>
                  <td className="right num">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

function SensitivityRow({
  row,
  shocks,
  maxAbsCoeff,
  onSelectSector,
}: {
  row: SectorSensitivityRow;
  shocks: string[];
  maxAbsCoeff: number;
  onSelectSector?: (sector: string) => void;
}) {
  const byShock = new Map(row.estimates.map((e) => [e.shock_name, e]));
  return (
    <tr>
      <th scope="row" style={rowHeadStyle}>
        {onSelectSector ? (
          <button className="btn-link" onClick={() => onSelectSector(row.sector)}>
            {row.sector}
          </button>
        ) : (
          row.sector
        )}
      </th>
      <td className="right num">{row.constituent_count}</td>
      {shocks.map((shock) => (
        <td key={shock} className="right" style={{ padding: 0 }}>
          <SensitivityCell estimate={byShock.get(shock)} maxAbsCoeff={maxAbsCoeff} />
        </td>
      ))}
    </tr>
  );
}

/** R1 T4.6.2 — background shading is the "heat" in "heat map": a
 * sequential MUTED scale (`--brand-100`..`--brand-400`, the same
 * tokens `Treemap` uses), never a red-green diverging scale, and
 * shading only applies to significant cells so a thin real history
 * never masquerades as a strong relationship via colour alone. */
function SensitivityCell({ estimate, maxAbsCoeff }: { estimate: SensitivityEstimate | undefined; maxAbsCoeff: number }) {
  if (!estimate) {
    // Not yet enough real history to test at all — a different fact
    // from "tested, not significant" below, so it gets a visually
    // distinct hollow mark rather than the same dash/label.
    return (
      <div style={{ padding: "var(--s2)", textAlign: "center" }}>
        <span
          aria-hidden
          title="Fewer than 20 real overlapping observations — not yet tested"
          style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", border: "1px solid var(--ink-4)" }}
        />
        <span className="visually-hidden">Not yet tested — too few real observations</span>
      </div>
    );
  }
  const coeff = Number(estimate.coefficient);
  const title = `p = ${Number(estimate.p_value).toFixed(3)}, R² = ${Number(estimate.r_squared).toFixed(3)}, n = ${estimate.observation_count}`;
  if (!estimate.significant) {
    // Tested, real data, coefficient not distinguishable from zero —
    // a filled hollow dot (vs. the outline-only "not yet tested" mark
    // above) so the two never read as the same fact.
    return (
      <div style={{ padding: "var(--s2)", textAlign: "center" }}>
        <span
          aria-hidden
          title={title}
          style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "var(--ink-4)" }}
        />
        <span className="visually-hidden">Tested, not significant. {title}</span>
      </div>
    );
  }
  const intensity = maxAbsCoeff > 0 ? Math.abs(coeff) / maxAbsCoeff : 0;
  const direction = estimate.direction_label === "positive" ? "up" : "down";
  return (
    <div style={{ padding: "var(--s2)", background: `color-mix(in srgb, var(--brand-300) ${(intensity * 60).toFixed(0)}%, transparent)` }}>
      <span className={`delta delta-${direction} num`} title={title}>
        <span aria-hidden="true">{direction === "up" ? "▲" : "▼"}</span> {coeff > 0 ? "+" : ""}
        {coeff.toFixed(4)}
      </span>
    </div>
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
