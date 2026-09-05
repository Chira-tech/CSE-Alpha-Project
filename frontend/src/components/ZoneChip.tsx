import { TapTip } from "./TapTip";
import type { PriceLadderZone } from "../types";

/** TASK 0.2: a null zone is a DIFFERENT, higher-stakes kind of missing
 * value than a generic missing number — "the zone is what a person
 * actually reads" (the brief's own words). It renders as this specific
 * literal, never the generic `UNAVAILABLE` ("Data unavailable") used for
 * an ordinary missing figure elsewhere in this app, and never a
 * default-substituted zone (§1 law 3 — never a nullish-coalesced literal
 * standing in for a missing zone; see scripts/check-no-zone-fallback.*
 * for the CI guard). */
export const NOT_YET_VALUED = "Not yet valued";

/**
 * §26's five zones as a small chip, reusing the same `--zone-*` tokens
 * `PriceLadder.tsx` defined for the full bar — the compact form used
 * anywhere a whole ladder is too much (a table row, a summary line).
 */
const ZONE_LABEL: Record<PriceLadderZone, string> = {
  strong_accumulate: "Strong accumulate",
  accumulate: "Accumulate",
  fair: "Fair",
  trim: "Trim",
  exit: "Exit",
};

const ZONE_TOKEN: Record<PriceLadderZone, string> = {
  strong_accumulate: "var(--zone-strong-accumulate)",
  accumulate: "var(--zone-accumulate)",
  fair: "var(--zone-fair)",
  trim: "var(--zone-trim)",
  exit: "var(--zone-exit)",
};

/** Zones where the position needs a decision now (§26) get a filled
 * chip; the informational ones stay outlined. Redesign spec §5 — "fill
 * weight conveys severity" — so the badge reads at a glance without a
 * second column. */
const FILLED: Record<PriceLadderZone, boolean> = {
  strong_accumulate: true,
  accumulate: false,
  fair: false,
  trim: true,
  exit: true,
};

export function ZoneChip({
  zone,
  why,
  compact = false,
}: {
  zone: PriceLadderZone | null;
  why?: string;
  /** Fixed width + single line + ellipsis, full label always in the
   * tooltip — for a table cell, where a wrapping two-word badge
   * ("Strong accumulate") was breaking row height. Non-compact callers
   * are unchanged. */
  compact?: boolean;
}) {
  if (!zone) {
    const reason = why || "No triangulated fair value is available for this ticker yet.";
    return (
      <TapTip label={reason}>
        <span
          className="muted"
          title={reason}
          style={
            compact
              ? { display: "inline-block", width: "8.5rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }
              : undefined
          }
        >
          {NOT_YET_VALUED}
        </span>
      </TapTip>
    );
  }
  const token = ZONE_TOKEN[zone];
  const filled = FILLED[zone];
  const tipLabel = compact ? `${ZONE_LABEL[zone]}${why ? ` — ${why}` : ""}` : why || "";
  return (
    <TapTip label={tipLabel}>
      <span
        className="chip"
        title={tipLabel || undefined}
        style={{
          borderColor: token,
          color: filled ? "var(--surface)" : token,
          background: filled ? token : "transparent",
          ...(compact
            ? {
                display: "inline-block",
                width: "8.5rem",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                textAlign: "center",
              }
            : {}),
        }}
      >
        {ZONE_LABEL[zone]}
      </span>
    </TapTip>
  );
}
