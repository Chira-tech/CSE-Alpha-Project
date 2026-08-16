import type { Evidence } from "./EvidencePanel";
import { ProvenanceChip } from "./ProvenanceChip";
import { EmptyState } from "./states";
import { UNAVAILABLE } from "../format";
import type { Ratio, UncomputableRatio } from "../types";

/**
 * §12's ratio set, with §5.1's display rules: percentages to one decimal,
 * ratios "with the unit named" (14.2× not 14.2), and anything missing
 * rendered as an explicit statement rather than a blank cell.
 *
 * Every row is clickable into the evidence panel (§14, "every number is a
 * door") because a ratio's whole value here is that you can see the two
 * figures underneath it.
 */
export function RatioTable({
  ratios,
  notComputable,
  periodEnd,
  onExplain,
}: {
  ratios: Ratio[];
  notComputable: UncomputableRatio[];
  periodEnd: string | null;
  onExplain: (evidence: Evidence) => void;
}) {
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
        <div className="table-wrap table-scroll">
          <table className="data-table">
            <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
              Computed from the statements for the period ending {periodEnd}. Click any ratio to see
              the figures underneath it.
            </caption>
            <thead>
              <tr>
                <th scope="col">Ratio</th>
                <th scope="col" className="right">Value</th>
                <th scope="col">Provenance</th>
              </tr>
            </thead>
            <tbody>
              {computable.map((r) => (
                <tr
                  key={r.key}
                  className="selectable"
                  tabIndex={0}
                  onClick={() => onExplain(toEvidence(r, periodEnd))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onExplain(toEvidence(r, periodEnd));
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
                  <td className="right num">{formatRatio(r)}</td>
                  <td>{r.provenance && <ProvenanceChip tier={r.provenance} />}</td>
                </tr>
              ))}
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

function toEvidence(r: Ratio, periodEnd: string): Evidence {
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
        Sector-relative percentiles and own-history trend arrive with the rest of the fundamental
        engine (§12–13). Both need several periods of history and a sector mapping, neither of which
        exists yet — so this figure currently stands alone, which is much less useful than it will
        be.
      </p>
    ),
    source: { label: `Filed financial statements, period ending ${periodEnd}` },
  };
}
