import { Delta } from "./Delta";
import { PlainExplainer } from "./PlainExplainer";
import type { Spread } from "../types";

// R1 T4.1.3 — three authored states, never a sentence generated from the
// number at runtime (§5.0's own copy rule). ±0.25pp is a real, disclosed
// "roughly level" band, not zero exactly — a spread of, say, +0.03pp
// is not meaningfully different from dead level and calling it "stocks
// pay more" would overstate a rounding-sized gap as a real edge.
const LEVEL_BAND_PP = 0.25;

function spreadExplainer(spreadPp: number, earningsYieldPct: string, tbillPct: string) {
  if (spreadPp > LEVEL_BAND_PP) {
    return {
      headline: "Stocks are paying more than bonds right now.",
      body: (
        <>
          Equity earnings yield {earningsYieldPct} vs 364-day T-bill {tbillPct}. When earnings
          yields beat risk-free rates, equities are being priced with a real margin over the safe
          alternative — historically a supportive backdrop, though this alone is not a signal to
          act on.
        </>
      ),
    };
  }
  if (spreadPp < -LEVEL_BAND_PP) {
    return {
      headline: "Bonds are paying more than stocks right now.",
      body: (
        <>
          Equity earnings yield {earningsYieldPct} vs 364-day T-bill {tbillPct}. When risk-free
          rates beat earnings yields, investors have less reason to pay up for equities, so
          valuations tend to compress. Historically this favours patience over new positions.
        </>
      ),
    };
  }
  return {
    headline: "Stocks and bonds are paying about the same right now.",
    body: (
      <>
        Equity earnings yield {earningsYieldPct} vs 364-day T-bill {tbillPct}. Neither side offers
        a clear valuation edge over the other at this level — the margin equities normally need
        over the risk-free alternative has narrowed.
      </>
    ),
  };
}

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
        <CoreTierNote spread={spread} />
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

      <PlainExplainer {...spreadExplainer(spreadPp, pct(spread.earnings_yield), pct(spread.tbill_yield))} />

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
          This T-bill yield was entered by hand rather than scraped. The CBSL scraper collects the
          primary-market auction yield automatically each day, so a manual figure here means that
          scheduled run hasn't reached this date yet. It is stored in the same point-in-time series
          as everything else and carries its source, so nothing here pretends to be live data.
        </p>
      )}

      {spread.history.length > 1 && <SpreadAreaChart history={spread.history} />}

      <CoreTierNote spread={spread} />
    </div>
  );
}

/**
 * TASK 3.3 (product-owner brief): this system's OWN Core-tier-restricted
 * `market_earnings_yield` — a second, additional read the brief asks
 * for on top of the exchange-published figure above, gated until >=100
 * real Core-tier companies exist. Honestly renders as a progress note,
 * never a fabricated chart, whichever state it's in — see the backend's
 * own `core_tier_hero_spread` docstring for exactly why it reads 0
 * today (§11.1 Gate 2 has no real free-float data source to read from
 * yet) rather than a stale or guessed count.
 */
function CoreTierNote({ spread }: { spread: Spread }) {
  if (spread.core_tier_available && spread.core_tier_market_earnings_yield !== null) {
    return (
      <p className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
        This system's own Core-tier earnings yield:{" "}
        {(Number(spread.core_tier_market_earnings_yield) * 100).toFixed(2)}% across{" "}
        {spread.core_tier_company_count} Core-tier companies.
      </p>
    );
  }
  return (
    <p className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
      {spread.core_tier_note}
    </p>
  );
}

/**
 * Macro page redesign spec §4 chart #2 — a diverging AREA chart around a
 * real zero baseline, not a bare sparkline under the headline number.
 * Zero is the meaningful threshold here (the point equities stop
 * out-yielding T-bills), so the fill — not just the line — carries which
 * side of it the spread sits on: warm (`--pos`) above zero (stocks
 * paying more), cool (`--neg`) below it (bonds paying more), at low
 * opacity so 2-3 years of daily crossings stay legible rather than
 * turning into a solid block of colour. Built with two clip-paths over
 * one shared area path rather than segmenting the series at every zero
 * crossing — the data has one shape, not N separate ones.
 */
function SpreadAreaChart({ history }: { history: Spread["history"] }) {
  const values = history.map((h) => Number(h.spread) * 100);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const width = 320;
  const height = 56;
  const clipId = "spread-area-clip";

  const coords = values.map((v, i) => ({
    x: (i / Math.max(values.length - 1, 1)) * width,
    y: height - ((v - min) / range) * height,
  }));
  const points = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");

  // §17 forbids "charts without a zero baseline where one is meaningful".
  // A spread crossing zero is exactly such a case — zero is the point at
  // which equities stop out-yielding the risk-free alternative.
  const zeroY = height - ((0 - min) / range) * height;
  const first = coords[0];
  const last = coords[coords.length - 1];
  const linePath = coords.map((c) => `L${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const areaPath =
    `M${first.x.toFixed(1)},${zeroY.toFixed(1)} ${linePath} ` +
    `L${last.x.toFixed(1)},${zeroY.toFixed(1)} Z`;

  return (
    <figure style={{ margin: "var(--s4) 0 0" }}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Spread over the last ${values.length} observations, shaded above zero when stocks pay more, below when bonds pay more`}
        style={{ maxWidth: "100%" }}
      >
        <defs>
          <clipPath id={`${clipId}-above`}>
            <rect x="0" y="0" width={width} height={zeroY} />
          </clipPath>
          <clipPath id={`${clipId}-below`}>
            <rect x="0" y={zeroY} width={width} height={height - zeroY} />
          </clipPath>
        </defs>
        <path d={areaPath} fill="var(--pos-bg)" clipPath={`url(#${clipId}-above)`} />
        <path d={areaPath} fill="var(--neg-bg)" clipPath={`url(#${clipId}-below)`} />
        <line x1="0" y1={zeroY} x2={width} y2={zeroY} stroke="var(--border-strong)" strokeDasharray="3 3" />
        <polyline points={points} fill="none" stroke="var(--brand-500)" strokeWidth="2" strokeLinejoin="round" />
      </svg>
      <figcaption className="t-caption">
        Dashed line is zero — the point at which equities stop out-yielding Treasury bills. Warm
        shading above it means stocks are paying more, cool shading below means bonds are.{" "}
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
