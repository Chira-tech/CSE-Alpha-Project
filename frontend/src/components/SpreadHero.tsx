import { Delta } from "./Delta";
import type { Spread } from "../types";

/**
 * Master Spec §29's hero: the equity earnings yield minus the 364-day
 * T-bill yield.
 *
 *   "CSE equity is priced as a substitute for Treasury bills... The
 *    equity earnings yield minus 364-day T-bill yield spread is therefore
 *    the single most powerful macro variable in the system... put it on
 *    the home screen as the hero chart."
 *
 * §8 of the UI spec is equally specific about why this and not the index:
 * "The index tells you what happened; the spread tells you whether
 * equities are cheap against the only alternative a Sri Lankan investor
 * genuinely has."
 *
 * The sparkline is inline SVG rather than a chart library: it is a
 * handful of points, and §4 caps chart animation at "500ms once on mount,
 * never re-animates on data refresh". A dependency would add weight
 * without adding honesty. Per §15.2 the figures are also exposed as a
 * table for assistive technology, since "all charts have an accessible
 * data-table equivalent behind a toggle — not a hidden alt-text summary,
 * the actual numbers".
 */
export function SpreadHero({ spread }: { spread: Spread }) {
  if (!spread.available) {
    return (
      <div className="notice notice-neutral">
        <h3>The hero spread cannot be computed yet</h3>
        <p className="prose t-body">
          §29 puts the equity-earnings-yield-minus-364-day-T-bill spread at the centre of this
          system — it is what tells you whether equities are cheap against the only real alternative
          a Sri Lankan investor has. It needs two inputs:
        </p>
        <ul className="not-built-list">
          {spread.missing.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      </div>
    );
  }

  const pct = (v: string | null) => (v === null ? "—" : `${(Number(v) * 100).toFixed(2)}%`);
  const spreadPp = Number(spread.spread) * 100;
  const isManual = (spread.tbill_source ?? "").toLowerCase().includes("manual");

  return (
    <div className="card">
      <span className="t-label">Equity earnings yield − 364-day T-bill</span>
      <div className="hero-value">
        {spreadPp > 0 ? "+" : ""}
        {spreadPp.toFixed(2)}pp
      </div>

      <p className="prose t-body" style={{ marginTop: "var(--s2)" }}>
        {spreadPp < 0
          ? "Equities are yielding less than risk-free Treasury bills. §29's framing: CSE equity is priced as a substitute for T-bills, so a negative spread is the market paying you less than the alternative."
          : "Equities are yielding more than risk-free Treasury bills."}
      </p>

      <table className="data-table" style={{ marginTop: "var(--s4)" }}>
        <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3) 0 0" }}>
          Market P/E {spread.market_per} as at {spread.obs_date}. T-bill observed{" "}
          {spread.tbill_obs_date}, source: {spread.tbill_source}.
        </caption>
        <tbody>
          <tr>
            <td style={{ color: "var(--ink-3)" }}>Market earnings yield (1 ÷ P/E)</td>
            <td className="right num">{pct(spread.earnings_yield)}</td>
          </tr>
          <tr>
            <td style={{ color: "var(--ink-3)" }}>364-day T-bill yield</td>
            <td className="right num">{pct(spread.tbill_yield)}</td>
          </tr>
          <tr>
            <td style={{ color: "var(--ink-3)" }}>Spread</td>
            <td className="right">
              <Delta percentage={spreadPp} />
            </td>
          </tr>
        </tbody>
      </table>

      {isManual && (
        <p className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
          The T-bill yield was entered by hand, not scraped — CBSL publishes it on
          JavaScript-rendered pages, so automated collection is a separate integration (§5). It is
          stored in the same point-in-time series as everything else and carries its source, so
          nothing here pretends to be live data.
        </p>
      )}

      {spread.history.length > 1 && <Sparkline history={spread.history} />}
    </div>
  );
}

function Sparkline({ history }: { history: Spread["history"] }) {
  const values = history.map((h) => Number(h.spread) * 100);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const width = 320;
  const height = 48;

  const points = values
    .map((v, i) => {
      const x = (i / Math.max(values.length - 1, 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  // §17 forbids "charts without a zero baseline where one is meaningful".
  // A spread crossing zero is exactly such a case — zero is the point at
  // which equities stop out-yielding the risk-free alternative.
  const zeroY = height - ((0 - min) / range) * height;

  return (
    <figure style={{ margin: "var(--s4) 0 0" }}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Spread over the last ${values.length} observations`}
        style={{ maxWidth: "100%" }}
      >
        <line
          x1="0"
          y1={zeroY}
          x2={width}
          y2={zeroY}
          stroke="var(--border-strong)"
          strokeDasharray="3 3"
        />
        <polyline
          points={points}
          fill="none"
          stroke="var(--brand-500)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
      </svg>
      <figcaption className="t-caption">
        Dashed line is zero — the point at which equities stop out-yielding Treasury bills.{" "}
        {values.length} observation{values.length === 1 ? "" : "s"} so far; this series accumulates
        forward, one trading day at a time.
      </figcaption>
      <details style={{ marginTop: "var(--s2)" }}>
        <summary className="t-caption" style={{ cursor: "pointer" }}>
          Show the figures
        </summary>
        <table className="data-table" style={{ marginTop: "var(--s2)" }}>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col" className="right">Earnings yield</th>
              <th scope="col" className="right">T-bill</th>
              <th scope="col" className="right">Spread</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.obs_date}>
                <td className="num">{h.obs_date}</td>
                <td className="right num">{(Number(h.earnings_yield) * 100).toFixed(2)}%</td>
                <td className="right num">{(Number(h.tbill_yield) * 100).toFixed(2)}%</td>
                <td className="right num">{(Number(h.spread) * 100).toFixed(2)}pp</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
