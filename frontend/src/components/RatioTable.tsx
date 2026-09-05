import type { Evidence } from "./EvidencePanel";
import { ProvenanceChip } from "./ProvenanceChip";
import { EmptyState } from "./states";
import { UNAVAILABLE } from "../format";
import type { Ratio, RatioPercentile, RatioTrend, UncomputableRatio } from "../types";

/**
 * §12's ratio set, with §5.1's display rules: percentages to one decimal,
 * ratios "with the unit named" (14.2× not 14.2), and anything missing
 * rendered as an explicit statement rather than a blank cell.
 *
 * Every row is clickable into the evidence panel (§14, "every number is a
 * door") because a ratio's whole value here is that you can see the two
 * figures underneath it.
 *
 * The Trend column is §13, and for most companies today it will read
 * "1 period" — most tickers have exactly one filing this system has ever
 * ingested (`getFinancialAnnouncement` is a recent-filings feed, not a
 * historical archive). That is not a bug in the column; it is the
 * honest state of the data, displayed rather than hidden, and it fills
 * in on its own as more periods accumulate.
 */
export function trendLabel(trend: RatioTrend | undefined): string {
  if (!trend || trend.direction === "insufficient_history") {
    const n = trend?.periods_used ?? 0;
    return n <= 1 ? `${n} period` : `${n} periods — too few for a trend`;
  }
  const arrow = trend.direction === "increasing" ? "▲" : trend.direction === "decreasing" ? "▼" : "→";
  const word = trend.direction === "no_trend" ? "no trend" : trend.direction;
  return `${arrow} ${word}${trend.significant ? "" : " (not significant)"}`;
}

/** §5.1-style: 1st/21st/82nd/100th, never a bare "82". */
function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

/** §12's sector-relative percentile — see `RatioPercentile`'s own
 * doc-comment for the ranking convention. `null` percentile always
 * carries a named reason (usually too few sector peers), shown instead
 * of a blank cell. */
export function percentileLabel(p: RatioPercentile | undefined): string {
  if (!p) return UNAVAILABLE;
  if (p.percentile === null) return p.reason ?? UNAVAILABLE;
  const pct = Math.round(Number(p.percentile));
  return `${ordinal(pct)} of ${p.group_label}${p.used_wider_sector ? " (wider sector)" : ""}`;
}

export function RatioTable({
  ratios,
  notComputable,
  periodEnd,
  trends = [],
  percentiles = [],
  onExplain,
}: {
  ratios: Ratio[];
  notComputable: UncomputableRatio[];
  periodEnd: string | null;
  trends?: RatioTrend[];
  percentiles?: RatioPercentile[];
  onExplain: (evidence: Evidence) => void;
}) {
  const trendByKey = new Map(trends.map((t) => [t.ratio_key, t]));
  const percentileByKey = new Map(percentiles.map((p) => [p.ratio_key, p]));
  const computable = ratios.filter((r) => r.value !== null);
  const blocked = ratios.filter((r) => r.value === null);

  if (periodEnd === null) {
    return (
      <EmptyState title="No financial statements ingested for this company.">
        <p style={{ margin: 0 }}>
          Ratios are computed from filed statements. Run the financial-statement scan, then confirm
          the extracted figures in the review queue — nothing enters a ratio until a human has
          approved it (§8).
        </p>
      </EmptyState>
    );
  }

  return (
    <div className="stack-tight">
      {computable.length > 0 && (
        <div className="table-wrap table-scroll table-scroll--cards">
          <table className="data-table">
            <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
              Computed from the statements for the period ending {periodEnd}. Click any ratio to see
              the figures underneath it.
            </caption>
            <thead>
              <tr>
                <th scope="col">Ratio</th>
                <th scope="col" className="right">Value</th>
                <th scope="col">Sector percentile (§12)</th>
                <th scope="col">Trend (§13)</th>
                <th scope="col">Provenance</th>
              </tr>
            </thead>
            <tbody>
              {computable.map((r) => {
                const percentile = percentileByKey.get(r.key);
                return (
                  <tr
                    key={r.key}
                    className="selectable"
                    tabIndex={0}
                    onClick={() => onExplain(toEvidence(r, periodEnd, percentile))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onExplain(toEvidence(r, periodEnd, percentile));
                      }
                    }}
                  >
                    <th
                      scope="row"
                      style={{
                        background: "none",
                        textTransform: "none",
                        letterSpacing: 0,
                        fontSize: 13,
                        fontWeight: 500,
                        color: "var(--ink-1)",
                      }}
                    >
                      {r.label}
                    </th>
                    <td className="right num" data-label="Value">{formatRatio(r)}</td>
                    <td
                      className={percentile?.percentile === null ? "t-caption muted" : "t-caption"}
                      data-label="Sector percentile"
                    >
                      {percentileLabel(percentile)}
                    </td>
                    <td className="t-caption" data-label="Trend">{trendLabel(trendByKey.get(r.key))}</td>
                    <td data-label="Provenance">{r.provenance && <ProvenanceChip tier={r.provenance} />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(blocked.length > 0 || notComputable.length > 0) && (
        <details className="card-sunken">
          <summary className="t-data" style={{ cursor: "pointer" }}>
            {blocked.length + notComputable.length} further ratio
            {blocked.length + notComputable.length === 1 ? "" : "s"} from §12 cannot be computed yet
          </summary>
          <p className="prose t-caption" style={{ marginTop: "var(--s3)" }}>
            Listed with what each one needs, rather than omitted — so the gap is visible and
            actionable instead of looking like the metric doesn't exist.
          </p>
          <table className="data-table" style={{ marginTop: "var(--s3)" }}>
            <thead>
              <tr>
                <th scope="col">Ratio</th>
                <th scope="col">Why not</th>
              </tr>
            </thead>
            <tbody>
              {blocked.map((r) => (
                <tr key={r.key}>
                  <th scope="row" style={rowHeadStyle}>{r.label}</th>
                  <td className="muted">
                    {r.missing_inputs.length > 0
                      ? `Missing line item${r.missing_inputs.length === 1 ? "" : "s"}: ${r.missing_inputs.join(", ")}`
                      : (r.note ?? UNAVAILABLE)}
                  </td>
                </tr>
              ))}
              {notComputable.map((r) => (
                <tr key={r.key}>
                  <th scope="row" style={rowHeadStyle}>{r.label}</th>
                  <td className="muted">Needs: {r.missing_inputs.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
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

/** §5.1: percentages to one decimal; ratios with the unit named. */
export function formatRatio(r: Ratio): string {
  if (r.value === null) return UNAVAILABLE;
  const n = Number(r.value);
  if (!Number.isFinite(n)) return UNAVAILABLE;
  if (r.unit === "percent") return `${(n * 100).toFixed(1)}%`;
  if (r.unit === "times") return `${n.toFixed(2)}×`;
  return n.toFixed(2);
}

export function toEvidence(r: Ratio, periodEnd: string, percentile: RatioPercentile | undefined): Evidence {
  return {
    title: r.label,
    whatItIs: `${r.label}, computed for the financial period ending ${periodEnd}.`,
    howItIsBuilt: (
      <p style={{ margin: 0 }}>
        <span className="mono">{r.formula}</span>
        {r.note ? ` — ${r.note}` : ""}
      </p>
    ),
    inputs: r.inputs_used.map((name) => ({ label: name, value: "see Financial statement lines" })),
    howItCompares: (
      <p style={{ margin: 0 }}>
        {percentile && percentile.percentile !== null ? (
          <>
            {ordinal(Math.round(Number(percentile.percentile)))} percentile within{" "}
            {percentile.group_label}
            {percentile.used_wider_sector
              ? " (the narrower CSE industry group had too few peers to rank against, so this falls back to the wider GICS sector)"
              : ""}
            , {percentile.group_size} peer{percentile.group_size === 1 ? "" : "s"} with a computable
            value for this ratio today (§12). Own-history trend is above, in the Trend column.
          </>
        ) : (
          <>
            {percentile?.reason ??
              "No sector-relative percentile yet for this ratio — see the Sector percentile column."}
          </>
        )}
      </p>
    ),
    source: { label: `Filed financial statements, period ending ${periodEnd}` },
  };
}
