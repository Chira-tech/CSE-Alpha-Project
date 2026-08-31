import { useMemo } from "react";
import type { RankedComposite } from "../types";

/**
 * Homepage redesign §6: "Distribution of price ÷ fair value across the
 * clean universe, with your holdings marked. One picture answering 'is
 * the market cheap, and where do I sit in it.'"
 *
 * Form per the `dataviz` heuristic: the data's job is a DISTRIBUTION, so
 * a histogram — vertical bars, one hue (`--brand-500`), never a rainbow.
 * The fair-value line (ratio = 1.00) is drawn once as the reference the
 * whole chart is read against; the median is a second rule; holdings are
 * a secondary mark (carets under their bin), never a colour change to
 * the bars. Volume-style dual axes and per-bar value labels are
 * deliberately absent (both on the anti-pattern list for a chart this
 * dense). Hover gives each bin's range and count; the caption carries
 * the figures so nothing is implied by shape alone.
 */
const LOW = 0.4;
const HIGH = 3.0;
const STEP = 0.2;

function ratioOf(row: RankedComposite): number | null {
  const price = row.current_price === null ? null : Number(row.current_price);
  const fv =
    row.blended_fair_value_per_share === null ? null : Number(row.blended_fair_value_per_share);
  if (price === null || fv === null || !Number.isFinite(price) || !Number.isFinite(fv) || fv <= 0)
    return null;
  return price / fv;
}

export function MarketValuationHistogram({
  rows,
  holdings,
}: {
  rows: RankedComposite[];
  /** Tickers the viewer holds — marked on the axis, never recoloured. */
  holdings?: Set<string>;
}) {
  const { bins, values, holdingRatios, median } = useMemo(() => {
    const withRatio = rows
      .map((r) => ({ ticker: r.ticker, ratio: ratioOf(r) }))
      .filter((r): r is { ticker: string; ratio: number } => r.ratio !== null);
    const vals = withRatio.map((r) => r.ratio).sort((a, b) => a - b);

    const edges: number[] = [];
    for (let e = LOW; e <= HIGH + 1e-9; e += STEP) edges.push(Number(e.toFixed(2)));
    const b = edges.slice(0, -1).map((lo, i) => ({ lo, hi: edges[i + 1], count: 0 }));
    const clamp = (x: number) => Math.min(HIGH - 1e-9, Math.max(LOW, x));
    for (const v of vals) {
      const idx = Math.min(b.length - 1, Math.floor((clamp(v) - LOW) / STEP));
      b[idx].count += 1;
    }
    const med = vals.length ? vals[Math.floor((vals.length - 1) / 2)] : null;
    const hr = withRatio
      .filter((r) => holdings?.has(r.ticker))
      .map((r) => ({ ticker: r.ticker, ratio: r.ratio }));
    return { bins: b, values: vals, holdingRatios: hr, median: med };
  }, [rows, holdings]);

  if (values.length < 5) {
    return (
      <p className="t-caption prose">
        Fewer than five companies have both a price and a blended fair value in the latest run —
        not enough to read a distribution yet.
      </p>
    );
  }

  const width = 640;
  const height = 150;
  const maxCount = Math.max(...bins.map((x) => x.count), 1);
  const xOf = (ratio: number) => ((ratio - LOW) / (HIGH - LOW)) * width;
  const barW = width / bins.length;

  const cheap = values.filter((v) => v < 1).length;
  const rich = values.length - cheap;

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Price divided by fair value for ${values.length} companies; median ${median?.toFixed(
          2,
        )}. ${cheap} trade below fair value, ${rich} at or above.`}
        style={{ width: "100%", height: "auto", display: "block", overflow: "visible" }}
      >
        {bins.map((bin, i) => {
          const h = (bin.count / maxCount) * (height - 24);
          return (
            <rect
              key={i}
              x={i * barW + 1}
              y={height - 16 - h}
              width={barW - 2}
              height={h}
              fill="var(--brand-500)"
              rx="1"
            >
              <title>
                {bin.lo.toFixed(1)}–{bin.hi.toFixed(1)}× fair value: {bin.count} compan
                {bin.count === 1 ? "y" : "ies"}
              </title>
            </rect>
          );
        })}

        {/* fair value — the line the whole chart is read against */}
        <line x1={xOf(1)} x2={xOf(1)} y1={0} y2={height - 16} stroke="var(--ink-2)" strokeWidth="1" />
        <text x={xOf(1)} y={10} textAnchor="middle" fontSize="10" fill="var(--ink-2)">
          fair
        </text>

        {median !== null && (
          <>
            <line
              x1={xOf(median)}
              x2={xOf(median)}
              y1={0}
              y2={height - 16}
              stroke="var(--ink-3)"
              strokeWidth="1"
              strokeDasharray="3 2"
            />
            <text
              x={xOf(median)}
              y={22}
              textAnchor="middle"
              fontSize="10"
              fill="var(--ink-3)"
            >
              median {median.toFixed(2)}
            </text>
          </>
        )}

        {/* axis ticks */}
        {[LOW, 1.0, 1.5, 2.0, 2.5, HIGH].map((t) => (
          <text key={t} x={xOf(t)} y={height - 2} textAnchor="middle" fontSize="9" fill="var(--ink-3)">
            {t.toFixed(1)}×
          </text>
        ))}

        {/* holdings — carets on the axis, never a bar recolour */}
        {holdingRatios.map((h) => {
          const x = xOf(Math.min(HIGH, Math.max(LOW, h.ratio)));
          return (
            <path
              key={h.ticker}
              d={`M${x - 4},${height - 16} L${x + 4},${height - 16} L${x},${height - 21} Z`}
              fill="var(--accent, var(--brand-300))"
            >
              <title>
                {h.ticker}: {h.ratio.toFixed(2)}× fair value
              </title>
            </path>
          );
        })}
      </svg>

      <figcaption className="t-caption prose" style={{ marginTop: "var(--s2)" }}>
        {values.length} companies with a price and a blended fair value. {cheap} trade below fair
        value, {rich} at or above; median {median?.toFixed(2)}×.
        {holdingRatios.length > 0
          ? ` Carets mark your ${holdingRatios.length} held position${
              holdingRatios.length === 1 ? "" : "s"
            }.`
          : ""}{" "}
        Bars outside {LOW.toFixed(1)}×–{HIGH.toFixed(1)}× are clamped into the end bins.
      </figcaption>
    </figure>
  );
}
