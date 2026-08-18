import { UNAVAILABLE } from "../format";
import type { PriceLadderZone } from "../types";

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

export function ZoneChip({ zone }: { zone: PriceLadderZone | null }) {
  if (!zone) return <span className="muted">{UNAVAILABLE}</span>;
  return (
    <span className="chip" style={{ borderColor: ZONE_TOKEN[zone], color: ZONE_TOKEN[zone] }}>
      {ZONE_LABEL[zone]}
    </span>
  );
}
