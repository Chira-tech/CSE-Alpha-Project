import { TapTip } from "./TapTip";
import type { ProvenanceTier } from "../types";

// UI spec §2.3/§5.3 — one token per tier, never a raw hex in a component.
const LABELS: Record<ProvenanceTier, string> = {
  R: "Reported",
  D: "Derived",
  N: "Normalised",
  E: "Estimated",
  F: "Forecast",
  A: "AI-assisted",
  "-": "Unavailable",
};

const TOKEN: Record<ProvenanceTier, string> = {
  R: "var(--prov-reported)",
  D: "var(--prov-derived)",
  N: "var(--prov-derived)",
  E: "var(--prov-estimated)",
  F: "var(--prov-estimated)",
  A: "var(--prov-ai)",
  "-": "var(--prov-missing)",
};

export function ProvenanceChip({ tier }: { tier: ProvenanceTier }) {
  return (
    <TapTip label={LABELS[tier]}>
      <span
        className="chip"
        style={{ borderColor: TOKEN[tier], color: TOKEN[tier] }}
        title={LABELS[tier]}
      >
        {tier}
      </span>
    </TapTip>
  );
}
