import { useState } from "react";
import type { Evidence } from "./EvidencePanel";
import { formatRatio, percentileLabel, toEvidence, trendLabel } from "./RatioTable";
import { ProvenanceDot } from "./ProvenanceDot";
import { VerdictPill, verdictFromPercentile } from "./VerdictPill";
import { EmptyState } from "./states";
import { directionGlyph, directionOf } from "../format";
import type { Ratio, RatioPercentile, RatioSeriesPoint, RatioTrend, UncomputableRatio } from "../types";

/**
 * R1 T4.3.1 — "Replace the numeric table with a card grid." Every card
 * carries: current value, prior-period value with direction, sector
 * percentile, a `VerdictPill`, and a path where >=3 periods exist —
 * directly implementing the spec principle that "ROE increased from
 * 11% -> 14% -> 16% -> 18%" beats "ROE = 18%" (§13).
 *
 * Grouping (Profitability / Growth / Financial strength / Efficiency /
 * Shareholder returns) is the brief's own taxonomy, not this app's ratio
 * engine's — `app.domain.ratios` has no notion of "group" today, so the
 * mapping lives here, in one place, and any ratio key it doesn't
 * recognise falls into "Other" rather than silently vanishing from the
 * page. Growth and Shareholder returns have zero computable ratios in
 * this system as of R1 (no revenue-growth or dividend ratio is wired in
 * `app.domain.ratios` yet) — shown as empty groups with the honest
 * reason, never hidden and never backfilled with something else's
 * numbers to look populated.
 */
const GROUP_ORDER = ["Profitability", "Growth", "Financial strength", "Efficiency", "Shareholder returns", "Other"] as const;
type Group = (typeof GROUP_ORDER)[number];

const GROUP_BY_KEY: Record<string, Group> = {
  return_on_equity: "Profitability",
  return_on_assets: "Profitability",
  gross_margin: "Profitability",
  operating_margin: "Profitability",
  net_margin: "Profitability",
  gross_profitability: "Profitability",
  roic: "Profitability",
  roic_wacc_spread: "Profitability",
  current_ratio: "Financial strength",
  liabilities_to_equity: "Financial strength",
  equity_ratio: "Financial strength",
  net_debt_to_ebitda: "Financial strength",
  interest_coverage: "Financial strength",
  altman_z: "Financial strength",
  effective_tax_rate: "Efficiency",
  cash_conversion: "Efficiency",
  operating_cash_flow_margin: "Efficiency",
  sloan_accrual_ratio: "Efficiency",
  piotroski_f_score: "Efficiency",
  beneish_m: "Efficiency",
};

const EMPTY_GROUP_NOTE: Partial<Record<Group, string>> = {
  Growth: "No revenue- or earnings-growth ratio is wired into this system's ratio engine yet — the composite score's own Growth pillar (below) uses a different, separate input set, not this table.",
  "Shareholder returns": "No dividend-yield or payout-ratio line is wired into this system's ratio engine yet — Corporate actions above lists real dividend events, but this system doesn't yet turn them into a ratio.",
};

export function RatioCardGrid({
  ratios,
  notComputable,
  periodEnd,
  trends = [],
  percentiles = [],
  series = {},
  onExplain,
}: {
  ratios: Ratio[];
  notComputable: UncomputableRatio[];
  periodEnd: string | null;
  trends?: RatioTrend[];
  percentiles?: RatioPercentile[];
  series?: Record<string, RatioSeriesPoint[]>;
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

  const byGroup = new Map<Group, Ratio[]>();
  for (const r of computable) {
    const g = GROUP_BY_KEY[r.key] ?? "Other";
    byGroup.set(g, [...(byGroup.get(g) ?? []), r]);
  }
  const notComputableByGroup = new Map<Group, { key: string; label: string; missing: string[] }[]>();
  for (const r of blocked) {
    const g = GROUP_BY_KEY[r.key] ?? "Other";
    notComputableByGroup.set(g, [
      ...(notComputableByGroup.get(g) ?? []),
      { key: r.key, label: r.label, missing: r.missing_inputs },
    ]);
  }
  for (const r of notComputable) {
    const g = GROUP_BY_KEY[r.key] ?? "Other";
    notComputableByGroup.set(g, [
      ...(notComputableByGroup.get(g) ?? []),
      { key: r.key, label: r.label, missing: r.missing_inputs },
    ]);
  }

  const groups = GROUP_ORDER.filter(
    (g) => (byGroup.get(g)?.length ?? 0) > 0 || (notComputableByGroup.get(g)?.length ?? 0) > 0 || EMPTY_GROUP_NOTE[g],
  );

  return (
    <div className="stack-tight">
      <p className="prose t-caption">
        Computed from the statements for the period ending {periodEnd}. Click any card to see the
        figures underneath it.
      </p>
      {groups.map((g) => (
        <RatioGroup
          key={g}
          group={g}
          cards={byGroup.get(g) ?? []}
          blocked={notComputableByGroup.get(g) ?? []}
          emptyNote={EMPTY_GROUP_NOTE[g]}
          periodEnd={periodEnd}
          trendByKey={trendByKey}
          percentileByKey={percentileByKey}
          series={series}
          onExplain={onExplain}
        />
      ))}
    </div>
  );
}

function RatioGroup({
  group,
  cards,
  blocked,
  emptyNote,
  periodEnd,
  trendByKey,
  percentileByKey,
  series,
  onExplain,
}: {
  group: Group;
  cards: Ratio[];
  blocked: { key: string; label: string; missing: string[] }[];
  emptyNote?: string;
  periodEnd: string;
  trendByKey: Map<string, RatioTrend>;
  percentileByKey: Map<string, RatioPercentile>;
  series: Record<string, RatioSeriesPoint[]>;
  onExplain: (evidence: Evidence) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <details className="card-sunken" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="t-data" style={{ cursor: "pointer" }}>
        {group} {cards.length > 0 ? `(${cards.length})` : ""}
      </summary>
      <div style={{ marginTop: "var(--s3)" }}>
        {cards.length === 0 && !emptyNote && blocked.length === 0 ? (
          <p className="prose t-caption muted">No ratios in this group yet.</p>
        ) : cards.length === 0 && emptyNote ? (
          <p className="prose t-caption muted">{emptyNote}</p>
        ) : (
          <div className="fact-grid">
            {cards.map((r) => (
              <RatioCard
                key={r.key}
                r={r}
                periodEnd={periodEnd}
                trend={trendByKey.get(r.key)}
                percentile={percentileByKey.get(r.key)}
                path={series[r.key]}
                onExplain={onExplain}
              />
            ))}
          </div>
        )}
        {blocked.length > 0 && (
          <details style={{ marginTop: "var(--s3)" }}>
            <summary className="t-caption" style={{ cursor: "pointer" }}>
              {blocked.length} further ratio{blocked.length === 1 ? "" : "s"} in this group cannot be
              computed yet
            </summary>
            <ul className="not-built-list" style={{ marginTop: "var(--s2)" }}>
              {blocked.map((b) => (
                <li key={b.key}>
                  {b.label} — {b.missing.length > 0 ? `needs: ${b.missing.join(", ")}` : "not yet computable"}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </details>
  );
}

function RatioCard({
  r,
  periodEnd,
  trend,
  percentile,
  path,
  onExplain,
}: {
  r: Ratio;
  periodEnd: string;
  trend: RatioTrend | undefined;
  percentile: RatioPercentile | undefined;
  path: RatioSeriesPoint[] | undefined;
  onExplain: (evidence: Evidence) => void;
}) {
  const pct = percentile?.percentile !== null && percentile?.percentile !== undefined ? Number(percentile.percentile) : null;
  const verdict = verdictFromPercentile(pct);

  const sorted = [...(path ?? [])].sort((a, b) => a.period_end.localeCompare(b.period_end));
  const last = sorted.at(-1);
  const prior = sorted.length >= 2 ? sorted[sorted.length - 2] : undefined;
  const priorDirection = prior && last ? directionOf(Number(last.value) - Number(prior.value)) : "unknown";

  return (
    <button
      className="card selectable"
      style={{ textAlign: "left", cursor: "pointer", border: "1px solid var(--border)" }}
      onClick={() => onExplain(toEvidence(r, periodEnd, percentile))}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--s2)" }}>
        <span className="t-label">{r.label}</span>
        <VerdictPill verdict={verdict} title={percentileLabel(percentile)} />
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--s2)", marginTop: "var(--s1)" }}>
        <span className="hero-value" style={{ fontSize: 22 }}>
          {formatRatio(r)}
        </span>
        {r.provenance && <ProvenanceDot tier={r.provenance} />}
      </div>
      {prior && (
        <p className="t-caption" style={{ marginTop: "var(--s1)" }}>
          Was {formatRatio({ ...r, value: prior.value })} at {prior.period_end}{" "}
          <span aria-hidden="true">{directionGlyph(priorDirection)}</span>
        </p>
      )}
      <p className="t-caption muted" style={{ marginTop: "var(--s1)" }}>
        Sector percentile: {percentileLabel(percentile)}
      </p>
      {sorted.length >= 3 ? (
        <RatioPath points={sorted} unit={r.unit} />
      ) : (
        <p className="t-caption muted" style={{ marginTop: "var(--s1)" }}>
          {sorted.length <= 1
            ? "Not enough periods for a path yet"
            : `${sorted.length} periods — one more unlocks a path`}
        </p>
      )}
      <p className="t-caption muted" style={{ marginTop: "var(--s1)" }}>{trendLabel(trend)}</p>
    </button>
  );
}

/** A real numeric path — "11 -> 14 -> 16 -> 18" — plus the matching
 * inline sparkline. Never drawn from fewer than 3 real periods (§13's
 * own `MIN_PERIODS_FOR_DIRECTION`), so a company with one filing shows
 * the honest "not enough periods" caption above instead of a two-point
 * line pretending to be a trend. */
function RatioPath({ points, unit }: { points: RatioSeriesPoint[]; unit: string }) {
  const values = points.map((p) => Number(p.value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 120;
  const h = 28;
  const stepX = points.length > 1 ? w / (points.length - 1) : 0;
  const coords = values.map((v, i) => {
    const x = i * stepX;
    const y = h - ((v - min) / span) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const fmt = (v: number) => (unit === "percent" ? `${(v * 100).toFixed(1)}%` : unit === "times" ? `${v.toFixed(2)}×` : v.toFixed(2));

  return (
    <div style={{ marginTop: "var(--s2)" }}>
      <svg width={w} height={h} aria-hidden="true" style={{ display: "block" }}>
        <polyline points={coords.join(" ")} fill="none" stroke="var(--brand-300)" strokeWidth={1.5} />
        {values.map((_v, i) => (
          <circle key={i} cx={coords[i].split(",")[0]} cy={coords[i].split(",")[1]} r={1.6} fill="var(--brand-300)" />
        ))}
      </svg>
      <p className="t-caption mono" style={{ marginTop: "var(--s1)" }}>
        {points.length > 8
          ? `${fmt(values[0])} … ${fmt(values.at(-1)!)} (${points.length} periods)`
          : values.map(fmt).join(" → ")}
      </p>
    </div>
  );
}
