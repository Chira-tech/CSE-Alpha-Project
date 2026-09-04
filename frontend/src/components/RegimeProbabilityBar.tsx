import type { RegimeGauge } from "../types";

/**
 * Macro page redesign spec §4 chart #1 — the regime's blended
 * probability as ONE horizontal segmented bar instead of three text
 * lines ("Risk-On 69.7% / Transition 10.2% / Risk-Off 20.0%"). Fixed
 * state order (never re-sorted by value, so the bar reads the same way
 * every visit) and the same `--regime-*` status tokens the rest of the
 * app already uses for this exact concept — Risk-On positive, Transition
 * caution/amber, Risk-Off slate (never red: a season, not an emergency,
 * per design-tokens.css's own comment on that token).
 *
 * Deliberately a stacked bar, not a gauge/speedometer (would dress up a
 * single percentage as more precise than a 2-state Markov fit plus a
 * rule-based composite actually is) and not a donut (three states in a
 * strip reads faster and stacks directly under the "Risk-On" headline
 * above it).
 */
const ORDER: { key: string; label: string; token: string }[] = [
  { key: "risk_on", label: "Risk-On", token: "var(--regime-risk-on)" },
  { key: "transition", label: "Transition", token: "var(--regime-transition)" },
  { key: "risk_off", label: "Risk-Off", token: "var(--regime-risk-off)" },
];

export function RegimeProbabilityBar({ gauge }: { gauge: RegimeGauge }) {
  const present = ORDER.filter((o) => gauge.probabilities[o.key] !== undefined);
  if (present.length === 0) return null;

  const values = new Map(present.map((o) => [o.key, Number(gauge.probabilities[o.key])]));

  return (
    <figure style={{ margin: 0 }}>
      <div
        style={{
          display: "flex",
          height: 14,
          borderRadius: 2,
          overflow: "hidden",
          gap: 2,
          background: "var(--surface-sunken)",
        }}
        role="img"
        aria-label={present
          .map((o) => `${o.label} ${(values.get(o.key)! * 100).toFixed(1)}%`)
          .join(", ")}
      >
        {present.map((o) => (
          <div
            key={o.key}
            style={{ flex: Math.max(values.get(o.key)!, 0.001), background: o.token }}
            title={`${o.label} ${(values.get(o.key)! * 100).toFixed(1)}%`}
          />
        ))}
      </div>
      <ul
        style={{
          listStyle: "none",
          margin: "var(--s2) 0 0",
          padding: 0,
          display: "flex",
          flexWrap: "wrap",
          gap: "var(--s1) var(--s4)",
          fontSize: 12,
        }}
      >
        {present.map((o) => (
          <li key={o.key} style={{ display: "flex", alignItems: "center", gap: "var(--s2)" }}>
            <span aria-hidden style={{ width: 10, height: 10, background: o.token, borderRadius: 2 }} />
            <span style={{ color: "var(--ink-2)" }}>{o.label}</span>
            <span className="num" style={{ color: "var(--ink-3)" }}>
              {(values.get(o.key)! * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
