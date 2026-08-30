/**
 * An axis-less, wordless trend line — the cheapest chart on the page and
 * the highest scan-value per pixel (Portfolio redesign spec §4). Same
 * inline-SVG, no-library idiom as `PriceHistoryChart`/`IndexHistoryChart`
 * (§4 caps chart motion at a single mount anyway), and the same §17
 * treatment: NOT zero-based (a share price has no meaningful zero), so
 * the line shows shape only and the real figures live in the row's
 * expandable detail, never implied by this mark.
 *
 * Draws nothing (returns a muted em dash) below two points — a
 * one-point "line" would be a fabricated flat trend.
 */
export function Sparkline({
  values,
  width = 72,
  height = 20,
  label,
}: {
  values: number[];
  width?: number;
  height?: number;
  label?: string;
}) {
  const clean = values.filter((v) => Number.isFinite(v));
  if (clean.length < 2) {
    return <span className="muted" aria-label="no trend data">—</span>;
  }

  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;
  const pad = 1.5;
  const path = clean
    .map((v, i) => {
      const x = pad + (i / (clean.length - 1)) * (width - pad * 2);
      const y = pad + (1 - (v - min) / range) * (height - pad * 2);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const first = clean[0];
  const last = clean[clean.length - 1];
  const dir = last > first ? "up" : last < first ? "down" : "flat";
  const stroke =
    dir === "up" ? "var(--pos)" : dir === "down" ? "var(--neg)" : "var(--ink-3)";

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={label ?? `trend, ${dir} over the window`}
      style={{ display: "block", overflow: "visible" }}
    >
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
