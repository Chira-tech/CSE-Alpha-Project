import { formatPrice } from "../format";
import type { PriceLadderOut } from "../types";

/**
 * §26: "five zones, derived, auditable... rendered as a single horizontal
 * bar with the current market price marked on it." The five
 * `--zone-*` tokens in design-tokens.css were defined against this exact
 * spec section before this component existed to use them — this is the
 * first thing in the app that reads them.
 */
const ZONES: { key: NonNullable<PriceLadderOut["current_zone"]>; label: string; token: string }[] = [
  { key: "strong_accumulate", label: "Strong accumulate", token: "var(--zone-strong-accumulate)" },
  { key: "accumulate", label: "Accumulate", token: "var(--zone-accumulate)" },
  { key: "fair", label: "Fair", token: "var(--zone-fair)" },
  { key: "trim", label: "Trim", token: "var(--zone-trim)" },
  { key: "exit", label: "Exit", token: "var(--zone-exit)" },
];

export function PriceLadder({ ladder }: { ladder: PriceLadderOut }) {
  const sa = Number(ladder.strong_accumulate_threshold);
  const bb = Number(ladder.buy_below_price);
  const trim = Number(ladder.trim_threshold);
  const exit = Number(ladder.exit_threshold);
  const current = ladder.current_price !== null ? Number(ladder.current_price) : null;

  // Strong-accumulate and exit are open-ended zones (< x, > y) — padding
  // gives each a visible width on the bar instead of collapsing to zero.
  const pad = Math.max(bb - sa, exit - trim, exit * 0.05, 1);
  const domainLow = sa - pad;
  const domainHigh = exit + pad;
  const span = domainHigh - domainLow || 1;
  const pct = (v: number) => Math.min(100, Math.max(0, ((v - domainLow) / span) * 100));

  const boundaries = [domainLow, sa, bb, trim, exit, domainHigh];
  const segments = ZONES.map((z, i) => ({
    ...z,
    widthPct: pct(boundaries[i + 1]) - pct(boundaries[i]),
  }));

  const gap = ladder.gap_to_buy_below_pct !== null ? Number(ladder.gap_to_buy_below_pct) : null;

  return (
    <div>
      <div
        role="img"
        aria-label={`Price ladder. Strong accumulate below ${formatPrice(String(sa))}. Accumulate to ${formatPrice(
          String(bb),
        )}. Fair to ${formatPrice(String(trim))}. Trim to ${formatPrice(String(exit))}. Exit above.${
          current !== null ? ` Current price ${formatPrice(String(current))}, in the ${ladder.current_zone} zone.` : ""
        }`}
        style={{
          display: "flex",
          height: 28,
          borderRadius: "var(--r-md)",
          overflow: "visible",
          position: "relative",
          border: "1px solid var(--border)",
        }}
      >
        <div style={{ display: "flex", width: "100%", borderRadius: "var(--r-md)", overflow: "hidden" }}>
          {segments.map((s) => (
            <div
              key={s.key}
              title={s.label}
              style={{
                width: `${s.widthPct}%`,
                background: s.token,
                opacity: ladder.current_zone === s.key ? 1 : 0.5,
              }}
            />
          ))}
        </div>
        {current !== null && (
          <div
            title={`Current: ${formatPrice(String(current))}`}
            style={{
              position: "absolute",
              left: `${pct(current)}%`,
              top: -4,
              bottom: -4,
              width: 2,
              background: "var(--ink-1)",
              transform: "translateX(-1px)",
            }}
          />
        )}
      </div>
      <div className="t-caption" style={{ display: "flex", justifyContent: "space-between", marginTop: "var(--s1)" }}>
        <span>Buy below {formatPrice(String(sa))}</span>
        <span>{formatPrice(String(bb))}</span>
        <span>Fair value {formatPrice(String(trim))}</span>
        <span>Stretch {formatPrice(String(exit))}</span>
      </div>
      {ladder.current_zone && ladder.zone_meaning && (
        <p className="prose t-body" style={{ marginTop: "var(--s3)" }}>
          <strong style={{ textTransform: "capitalize" }}>{ladder.current_zone.replace(/_/g, " ")}</strong> —{" "}
          {ladder.zone_meaning}
          {gap !== null && (
            <>
              {" "}
              ({Math.abs(gap * 100).toFixed(0)}% {gap >= 0 ? "above" : "below"} your buy-below price)
            </>
          )}
        </p>
      )}
    </div>
  );
}
