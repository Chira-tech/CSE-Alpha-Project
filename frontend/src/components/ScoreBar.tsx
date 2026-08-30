/**
 * A 0-100 score as a small horizontal fill bar. This is a genuine
 * "part of a whole vs. a threshold" use of a chart (the redesign doc's
 * §1.2) — relative strength is readable without parsing digits — not a
 * gauge/speedometer, which would be pure decoration for one number.
 *
 * Colour is NOT the carrier of meaning here: the numeral sits right
 * beside the bar, and the fill is a single neutral brand tone at every
 * value (never red/green — §1 law 6 reserves those for real
 * gain/loss). A muted em dash when there is no score, never a zero-width
 * bar that could read as "scored zero".
 */
export function ScoreBar({
  score,
  width = 132,
  compact = false,
}: {
  score: number | null;
  width?: number;
  /** Thinner bar + no inline numeral — for the pillar breakdown rows,
   * where the number lives in its own column. */
  compact?: boolean;
}) {
  if (score === null || !Number.isFinite(score)) {
    return <span className="muted">—</span>;
  }
  const pct = Math.max(0, Math.min(100, score));
  const barWidth = compact ? width : width * 0.62;

  const bar = (
    <span
      aria-hidden="true"
      style={{
        position: "relative",
        display: "inline-block",
        width: barWidth,
        height: compact ? 6 : 8,
        background: "var(--surface-sunken)",
        borderRadius: "var(--r-sm)",
        border: "1px solid var(--border)",
        verticalAlign: "middle",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: `${pct}%`,
          background: "var(--brand-500)",
          borderRadius: "var(--r-sm)",
        }}
      />
    </span>
  );

  if (compact) return bar;

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--s2)", justifyContent: "flex-end" }}>
      {bar}
      <span className="num" style={{ fontWeight: 600, minWidth: "2.2ch", textAlign: "right" }}>
        {Math.round(pct)}
      </span>
    </span>
  );
}
