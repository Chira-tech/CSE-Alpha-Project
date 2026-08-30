import { useState } from "react";
import { formatMagnitude } from "../format";

/**
 * Where the money actually sits — by holding, or by sector. The old
 * screen showed concentration nowhere; a part-to-whole relationship is
 * what a donut encodes honestly, and at ~9 holdings it stays readable
 * (a donut with 30 slices would not — this is the "only if relevant"
 * call). Beyond the seventh slice everything folds into one "Other"
 * wedge rather than cycling colours, so hue always means the same
 * entity.
 *
 * Colours are the design system's own ordered categorical ramp
 * (`--cat-1..8`, "ordered by perceptual distance" in design-tokens.css),
 * assigned in fixed order and never cycled. Every value/label stays in
 * an ink token — the wedge beside it carries identity, not the text.
 * Unpriced positions are excluded from the whole and named below the
 * chart rather than silently dropped.
 */
export interface AllocationSlice {
  key: string;
  label: string;
  value: number;
}

const CAT = [
  "var(--cat-1)",
  "var(--cat-2)",
  "var(--cat-3)",
  "var(--cat-4)",
  "var(--cat-5)",
  "var(--cat-6)",
  "var(--cat-7)",
];
const OTHER_COLOR = "var(--cat-8)";
const MAX_SLICES = 7;

function foldToOther(slices: AllocationSlice[]): (AllocationSlice & { color: string })[] {
  const sorted = [...slices].filter((s) => s.value > 0).sort((a, b) => b.value - a.value);
  if (sorted.length <= MAX_SLICES) {
    return sorted.map((s, i) => ({ ...s, color: CAT[i] }));
  }
  const head = sorted.slice(0, MAX_SLICES).map((s, i) => ({ ...s, color: CAT[i] }));
  const tail = sorted.slice(MAX_SLICES);
  const otherValue = tail.reduce((a, b) => a + b.value, 0);
  return [
    ...head,
    { key: "__other__", label: `Other (${tail.length})`, value: otherValue, color: OTHER_COLOR },
  ];
}

function arc(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const p = (a: number) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
}

export function AllocationDonut({
  byHolding,
  bySector,
  unpricedCount = 0,
}: {
  byHolding: AllocationSlice[];
  bySector: AllocationSlice[];
  unpricedCount?: number;
}) {
  const [mode, setMode] = useState<"holding" | "sector">("holding");
  const source = mode === "holding" ? byHolding : bySector;
  const slices = foldToOther(source);
  const total = slices.reduce((a, b) => a + b.value, 0);

  if (total <= 0) {
    return (
      <p className="prose t-caption muted">
        No live-priced holdings to size an allocation from yet.
      </p>
    );
  }

  const size = 168;
  const r = 70;
  const stroke = 22;
  const cx = size / 2;
  const cy = size / 2;
  let angle = -Math.PI / 2;
  const segments = slices.map((s) => {
    const sweep = (s.value / total) * Math.PI * 2;
    const d = arc(cx, cy, r, angle, angle + sweep - 0.02);
    angle += sweep;
    return { ...s, d, pct: (s.value / total) * 100 };
  });

  return (
    <figure style={{ margin: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span className="t-label">Allocation</span>
        <div role="group" aria-label="Group allocation by">
          {(["holding", "sector"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              style={{
                border: "1px solid var(--border-strong)",
                background: mode === m ? "var(--brand-50)" : "transparent",
                color: mode === m ? "var(--brand-700)" : "var(--ink-3)",
                padding: "2px var(--s2)",
                fontSize: 12,
                textTransform: "capitalize",
                cursor: "pointer",
              }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: "var(--s4)", alignItems: "center", marginTop: "var(--s3)", flexWrap: "wrap" }}>
        <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label={`Allocation by ${mode}`}>
          {segments.map((s) => (
            <path key={s.key} d={s.d} fill="none" stroke={s.color} strokeWidth={stroke} strokeLinecap="butt">
              <title>{`${s.label}: ${formatMagnitude(s.value)} (${s.pct.toFixed(1)}%)`}</title>
            </path>
          ))}
        </svg>

        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--s1)", minWidth: 160 }}>
          {segments.map((s) => (
            <li key={s.key} style={{ display: "flex", alignItems: "center", gap: "var(--s2)", fontSize: 12 }}>
              <span
                aria-hidden
                style={{ width: 10, height: 10, background: s.color, borderRadius: 2, flexShrink: 0 }}
              />
              <span style={{ color: "var(--ink-2)", flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {s.label}
              </span>
              <span className="num" style={{ color: "var(--ink-3)" }}>{s.pct.toFixed(0)}%</span>
            </li>
          ))}
        </ul>
      </div>

      {unpricedCount > 0 && (
        <p className="t-caption muted" style={{ marginTop: "var(--s2)" }}>
          {unpricedCount} position{unpricedCount === 1 ? "" : "s"} with no live price {unpricedCount === 1 ? "is" : "are"} excluded
          from this split rather than counted at a guessed value.
        </p>
      )}
    </figure>
  );
}
