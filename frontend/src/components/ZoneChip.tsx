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

export function ZoneChip({ zone, why }: { zone: PriceLadderZone | null; why?: string }) {
  if (!zone) {
    return (
      <span className="muted" title={why || "No triangulated fair value is available for this ticker yet."}>
        {NOT_YET_VALUED}
      </span>
    );
  }
  return (
    <span className="chip" style={{ borderColor: ZONE_TOKEN[zone], color: ZONE_TOKEN[zone] }}>
      {ZONE_LABEL[zone]}
    </span>
  );
}
