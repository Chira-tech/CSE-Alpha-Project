import { directionGlyph, directionOf, formatPercent, UNAVAILABLE } from "../format";

/**
 * UI spec §5.2: directional colour appears ONLY in small text, thin bars
 * and small chips — never a row background, never a banner, never more
 * than ~5% of the viewport. This component is the only place directional
 * colour is applied, which is what keeps that rule enforceable.
 */
export function Delta({ percentage }: { percentage: number | null | undefined }) {
  const direction = directionOf(percentage);
  if (direction === "unknown") return <span className="muted">{UNAVAILABLE}</span>;
  return (
    <span className={`delta delta-${direction} num`}>
      <span aria-hidden="true">{directionGlyph(direction)}</span> {formatPercent(percentage)}
    </span>
  );
}
