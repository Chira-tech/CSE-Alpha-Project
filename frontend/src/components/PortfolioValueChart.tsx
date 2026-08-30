import { useState } from "react";
import { formatMagnitude, formatPercent } from "../format";
import type { ValuePoint } from "../types";

/**
 * The portfolio's own value over time — today's exact holdings priced at
 * each past real close (the honest question a system with no transaction
 * log can answer; see the backend's `portfolio_value_series` docstring).
 * Replaces the three lonely "15D / 30D / 45D" numbers the old screen
 * showed: those numbers *were* a time series someone already computed,
 * and the shape of the journey (a steady climb vs. one volatile spike)
 * is exactly what the text couldn't show.
 *
 * Same inline-SVG, no-library idiom as `IndexHistoryChart`
 * (§4 caps chart motion at a single mount) and the same §17 treatment:
 * the vertical axis is NOT zero-based — a portfolio worth ~76k has no
 * meaningful zero and a zero-based axis would flatten every real move —
 * so the real range is stated in the caption rather than implied by the
 * shape. A faint constant line marks total cost so "am I above or below
 * what I paid" is readable at a glance without colour alone carrying it.
 */
const WINDOWS = [
  { label: "15D", days: 15 },
  { label: "30D", days: 30 },
  { label: "45D", days: 45 },
  { label: "90D", days: 90 },
] as const;

export function PortfolioValueChart({
  series,
  totalCost,
}: {
  series: ValuePoint[];
  totalCost: number;
}) {
  const [windowDays, setWindowDays] = useState<number>(45);

  if (series.length < 2) {
    return (
      <p className="prose t-caption muted">
        Not enough real price history across the current holdings to chart the portfolio's value
        over time yet — the newest holding's stored history has to reach back across the whole
        window for a point to be real rather than guessed.
      </p>
    );
  }

  const lastDate = new Date(series[series.length - 1].date).getTime();
  const cutoff = lastDate - windowDays * 24 * 3600 * 1000;
  const shown = series.filter((p) => new Date(p.date).getTime() >= cutoff);
  const points = shown.length >= 2 ? shown : series;

  const values = points.map((p) => Number(p.value));
  const lo = Math.min(...values, totalCost);
  const hi = Math.max(...values, totalCost);
  const range = hi - lo || 1;
  const width = 640;
  const height = 200;

  const xy = (i: number, v: number) => {
    const x = (i / (points.length - 1)) * width;
    const y = height - ((v - lo) / range) * height;
    return [x, y] as const;
  };

  const line = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${xy(i, v).map((n) => n.toFixed(1)).join(",")}`)
    .join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  const costY = height - ((totalCost - lo) / range) * height;

  const first = points[0];
  const last = points[points.length - 1];
  const changePct = ((Number(last.value) - Number(first.value)) / Number(first.value)) * 100;
  const endValue = Number(last.value);
  const vsCostPct = ((endValue - totalCost) / totalCost) * 100;

  return (
    <figure style={{ margin: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "var(--s3)" }}>
        <div>
          <span className="t-label">Portfolio value</span>
          <div className="hero-value" style={{ fontSize: 24 }}>
            {formatMagnitude(endValue)}
          </div>
          <div className="t-caption">
            {formatPercent(changePct)} over {points.length} points ·{" "}
            {vsCostPct >= 0 ? "+" : ""}
            {vsCostPct.toFixed(1)}% vs. cost
          </div>
        </div>
        <div className="segmented" role="group" aria-label="Chart window">
          {WINDOWS.map((w) => (
            <button
              key={w.label}
              type="button"
              aria-pressed={windowDays === w.days}
              className={windowDays === w.days ? "seg seg-active" : "seg"}
              onClick={() => setWindowDays(w.days)}
              style={{
                border: "1px solid var(--border-strong)",
                background: windowDays === w.days ? "var(--brand-50)" : "transparent",
                color: windowDays === w.days ? "var(--brand-700)" : "var(--ink-3)",
                padding: "2px var(--s2)",
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Portfolio value from ${first.date} to ${last.date}, ranging ${formatMagnitude(
          Math.min(...values),
        )} to ${formatMagnitude(Math.max(...values))}, against a total cost of ${formatMagnitude(totalCost)}`}
        style={{ width: "100%", height: "auto", display: "block", marginTop: "var(--s3)" }}
      >
        <path d={area} fill="var(--brand-50)" stroke="none" />
        <path d={line} fill="none" stroke="var(--brand-500)" strokeWidth="1.5" strokeLinejoin="round" />
        {costY >= 0 && costY <= height && (
          <line
            x1="0"
            x2={width}
            y1={costY.toFixed(1)}
            y2={costY.toFixed(1)}
            stroke="var(--ink-3)"
            strokeWidth="1"
            strokeDasharray="4 3"
          />
        )}
      </svg>

      <div className="t-caption" style={{ display: "flex", justifyContent: "space-between", marginTop: "var(--s2)" }}>
        <span className="num">{first.date}</span>
        <span className="num">
          {formatMagnitude(Math.min(...values))} – {formatMagnitude(Math.max(...values))}
        </span>
        <span className="num">{last.date}</span>
      </div>

      <figcaption className="t-caption prose" style={{ marginTop: "var(--s2)" }}>
        Today's holdings priced at each past real close — not a transaction replay (this system has
        no transaction log). The dashed line is total cost ({formatMagnitude(totalCost)}). The
        vertical axis is not zero-based; the range is stated above rather than implied by the shape.
      </figcaption>

      <details style={{ marginTop: "var(--s3)" }}>
        <summary className="t-caption" style={{ cursor: "pointer" }}>
          Show the figures
        </summary>
        <div className="table-wrap table-scroll" style={{ maxHeight: 260, marginTop: "var(--s2)" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col" className="right">Value</th>
              </tr>
            </thead>
            <tbody>
              {[...points].reverse().map((p) => (
                <tr key={p.date}>
                  <td className="num">{p.date}</td>
                  <td className="right num">{formatMagnitude(Number(p.value))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
