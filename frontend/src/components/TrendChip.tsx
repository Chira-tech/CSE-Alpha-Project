import { directionGlyph, directionOf, formatPercent } from "../format";

export interface TrendWindow {
  /** e.g. "15d" */
  label: string;
  /** Signed percentage change over this window, or `null` if not enough
   * real history exists yet for it — rendered as a named gap, never a
   * fabricated 0%. */
  pct: number | null;
}

/**
 * R1 brief §5.0 — a horizontal strip of window/change pairs (15d / 30d /
 * 45d, sometimes 60d), reusing `Delta`'s own hue+glyph+lightness
 * discipline per window so direction is never colour-only. One missing
 * window renders "Data unavailable" for that window alone, not the whole
 * strip.
 */
export function TrendChip({ windows }: { windows: TrendWindow[] }) {
  return (
    <div className="row" style={{ gap: "var(--s4)", flexWrap: "wrap" }} role="group" aria-label="Trend by window">
      {windows.map((w) => {
        const direction = directionOf(w.pct);
        return (
          <div key={w.label} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span className="t-label">{w.label}</span>
            {direction === "unknown" ? (
              <span className="muted t-caption">Data unavailable</span>
            ) : (
              <span className={`delta delta-${direction} num`}>
                <span aria-hidden="true">{directionGlyph(direction)}</span> {formatPercent(w.pct)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
