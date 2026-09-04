import type { IndexHistory, RegimeHistoryPoint } from "../types";

const REGIME_TOKEN: Record<string, string> = {
  risk_on: "var(--regime-risk-on)",
  transition: "var(--regime-transition)",
  risk_off: "var(--regime-risk-off)",
};
const REGIME_LABEL_TEXT: Record<string, string> = {
  risk_on: "Risk-On",
  transition: "Transition",
  risk_off: "Risk-Off",
};

/**
 * A year of ASPI closes.
 *
 * Deliberately NOT the hero. UI spec §8 is explicit that the index is the
 * lesser variable — "the index tells you what happened; the spread tells
 * you whether equities are cheap against the only alternative a Sri
 * Lankan investor genuinely has." This sits below the spread and is
 * framed as context, not as a signal.
 *
 * Inline SVG for the same reason as SpreadHero: a chart library would add
 * weight without adding honesty, and §4 caps chart motion at a single
 * 500ms mount animation anyway.
 *
 * §17 forbids "charts without a zero baseline where one is meaningful".
 * Zero is NOT meaningful for an index level — the ASPI has never been
 * near it and a zero-based axis would compress a year of real movement
 * into a flat line. The axis is therefore labelled with its actual
 * minimum and maximum so the scale is stated rather than implied, which
 * is what the anti-pattern is protecting against.
 *
 * Macro page redesign spec §4 chart #5 — `regimeHistory`, when supplied,
 * shades a low-opacity background band per classified day behind the
 * price line, using the same `--regime-*` tokens `RegimeProbabilityBar`
 * does — the price chart and the regime call above it become one
 * connected story instead of two unrelated widgets. Joined onto the
 * price points by real calendar date (a `Map` lookup, never assumed
 * aligned by position — the two series come from different code paths
 * over the same underlying data and are not guaranteed to share every
 * date); an ASPI date the regime fit's own window doesn't cover is
 * simply left unshaded rather than guessed. This is the Markov-only
 * statistical path, not the 50/50 blend the current-day label is — see
 * `RegimeGauge.history_note`, surfaced in the caption below when present.
 */
export function IndexHistoryChart({
  history,
  regimeHistory,
}: {
  history: IndexHistory;
  regimeHistory?: RegimeHistoryPoint[];
}) {
  const points = history.points;
  if (points.length < 2) return null;

  const values = points.map((p) => Number(p.value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 720;
  const height = 180;

  const regimeByDate = new Map((regimeHistory ?? []).map((r) => [r.date, r.label]));
  const hasShading = regimeByDate.size > 0;

  // One band per contiguous run of the same label, spanning from this
  // point's own x through the NEXT point's x (so adjacent bands meet
  // with no gap) — built once, rendered behind the line and axis.
  const bands: { x0: number; x1: number; label: string }[] = [];
  if (hasShading) {
    let current: { x0: number; label: string } | null = null;
    points.forEach((p, i) => {
      const x = (i / Math.max(points.length - 1, 1)) * width;
      const label = regimeByDate.get(p.obs_date);
      if (label === undefined) {
        if (current) {
          bands.push({ x0: current.x0, x1: x, label: current.label });
          current = null;
        }
        return;
      }
      if (!current || current.label !== label) {
        if (current) bands.push({ x0: current.x0, x1: x, label: current.label });
        current = { x0: x, label };
      }
      if (i === points.length - 1) {
        bands.push({ x0: current.x0, x1: width, label: current.label });
      }
    });
  }

  const path = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const first = points[0];
  const last = points[points.length - 1];
  const changePct = ((Number(last.value) - Number(first.value)) / Number(first.value)) * 100;

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={
          `ASPI closing level from ${first.obs_date} to ${last.obs_date}, ranging between ` +
          `${min.toFixed(2)} and ${max.toFixed(2)}` +
          (hasShading ? ", shaded by the statistical regime read on each trading day" : "")
        }
        style={{ width: "100%", height: "auto", display: "block" }}
      >
        {bands.map((b, i) => (
          <rect
            key={i}
            x={b.x0}
            y={0}
            width={Math.max(b.x1 - b.x0, 0)}
            height={height}
            fill={REGIME_TOKEN[b.label] ?? "var(--ink-4)"}
            opacity={0.12}
          />
        ))}
        <path d={path} fill="none" stroke="var(--brand-500)" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>

      {hasShading && (
        <ul
          style={{ listStyle: "none", margin: "var(--s2) 0 0", padding: 0, display: "flex", gap: "var(--s4)", fontSize: 12 }}
        >
          {["risk_on", "transition", "risk_off"].map((label) => (
            <li key={label} style={{ display: "flex", alignItems: "center", gap: "var(--s2)" }}>
              <span aria-hidden style={{ width: 10, height: 10, background: REGIME_TOKEN[label], borderRadius: 2 }} />
              <span style={{ color: "var(--ink-2)" }}>{REGIME_LABEL_TEXT[label]}</span>
            </li>
          ))}
        </ul>
      )}

      <div
        className="t-caption"
        style={{ display: "flex", justifyContent: "space-between", marginTop: "var(--s2)" }}
      >
        <span className="num">{first.obs_date}</span>
        <span className="num">
          {min.toFixed(2)} – {max.toFixed(2)}
        </span>
        <span className="num">{last.obs_date}</span>
      </div>

      <figcaption className="t-caption prose" style={{ marginTop: "var(--s2)" }}>
        {points.length} closes, {changePct >= 0 ? "+" : ""}
        {changePct.toFixed(1)}% over the period. The vertical axis spans {min.toFixed(2)} to{" "}
        {max.toFixed(2)} and is not zero-based — an index level has no meaningful zero, so the
        range is stated here rather than implied by the shape.
        {hasShading &&
          " Background shading is the statistical (Markov-switching) regime read for each day — " +
            "not the full 50/50 blend the current-day call above uses, which also weighs the " +
            "macro composite; that half has no historical path of its own."}
      </figcaption>

      {history.recovered > 0 && (
        <p className="t-caption prose" style={{ marginTop: "var(--s2)" }}>
          {history.recovered} of {points.length} closes were reconstructed from the feed&rsquo;s
          published percentage change rather than read directly, because on those days cse.lk
          stamps a pre-open level rather than the close. The reconstruction was checked against the
          Central Bank&rsquo;s independently published ASPI and matched exactly, while the raw
          figure was out by up to 49 index points.
        </p>
      )}

      <details style={{ marginTop: "var(--s3)" }}>
        <summary className="t-caption" style={{ cursor: "pointer" }}>
          Show the figures
        </summary>
        <div className="table-wrap table-scroll" style={{ maxHeight: 320, marginTop: "var(--s2)" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col" className="right">Close</th>
                <th scope="col">Reading</th>
              </tr>
            </thead>
            <tbody>
              {[...points].reverse().map((p) => (
                <tr key={p.obs_date}>
                  <td className="num">{p.obs_date}</td>
                  <td className="right num">{Number(p.value).toFixed(2)}</td>
                  <td className="t-caption">
                    {p.source.endsWith("(pc)") ? "recovered" : "direct"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
