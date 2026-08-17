import type { PricePoint } from "../types";

/**
 * A company's stored close-price history, chronological.
 *
 * Same shape and reasoning as IndexHistoryChart on the Macro screen: an
 * inline SVG line rather than a chart library (§4 caps chart animation at
 * a single 500ms mount, so a dependency buys nothing), and the vertical
 * axis is NOT zero-based with its real range printed in the caption — §17
 * forbids "charts without a zero baseline where one is meaningful", and
 * zero is not meaningful for a share price any more than an index level
 * is: a zero-based axis on, say, a stock trading in the 40-60 range would
 * flatten a real 20% move into a sliver.
 *
 * Plots the RAW stored close, not the adjustment-factor-adjusted close.
 * The table below this chart shows both `close` and `adj_factor`
 * separately, and most tickers currently carry `adj_factor = 1.0` (the
 * backwards-rebuild job that would change that on a confirmed corporate
 * action is Phase-1 remaining work — see ROADMAP.md) — showing anything
 * else here would imply a total-return series this system does not yet
 * compute.
 */
export function PriceHistoryChart({ history }: { history: PricePoint[] }) {
  const points = history
    .filter((p): p is PricePoint & { close: string } => p.close !== null)
    .map((p) => ({ date: p.date, value: Number(p.close) }));

  if (points.length < 2) return null;

  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 720;
  const height = 140;

  const path = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const first = points[0];
  const last = points[points.length - 1];
  const changePct = ((last.value - first.value) / first.value) * 100;
  const skipped = history.length - points.length;

  return (
    <figure style={{ margin: "0 0 var(--s4)" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Close price from ${first.date} to ${last.date}, ranging between ${min.toFixed(2)} and ${max.toFixed(2)} LKR`}
        style={{ width: "100%", height: "auto", display: "block" }}
      >
        <path d={path} fill="none" stroke="var(--brand-500)" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>

      <div
        className="t-caption"
        style={{ display: "flex", justifyContent: "space-between", marginTop: "var(--s2)" }}
      >
        <span className="num">{first.date}</span>
        <span className="num">
          {min.toFixed(2)} – {max.toFixed(2)} LKR
        </span>
        <span className="num">{last.date}</span>
      </div>

      <figcaption className="t-caption prose" style={{ marginTop: "var(--s2)" }}>
        {points.length} session{points.length === 1 ? "" : "s"}, {changePct >= 0 ? "+" : ""}
        {changePct.toFixed(1)}% over the period. Raw stored close, not adjusted for corporate
        actions — see the adjustment factor column below. The vertical axis is not zero-based; its
        range is stated above rather than implied by the shape.
        {skipped > 0 &&
          ` ${skipped} stored session${skipped === 1 ? "" : "s"} with no close recorded are excluded from this chart.`}
      </figcaption>
    </figure>
  );
}
