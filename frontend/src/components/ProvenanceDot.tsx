import type { ProvenanceTier } from "../types";

const LABELS: Record<ProvenanceTier, string> = {
  R: "Reported",
  D: "Derived",
  N: "Normalised",
  E: "Estimated",
  F: "Forecast",
  A: "AI-assisted",
  "-": "Unavailable",
};

// Same tokens `ProvenanceChip` already uses — one definition, reused,
// never a second palette for the same seven tiers.
const TOKEN: Record<ProvenanceTier, string> = {
  R: "var(--prov-reported)",
  D: "var(--prov-derived)",
  N: "var(--prov-derived)",
  E: "var(--prov-estimated)",
  F: "var(--prov-estimated)",
  A: "var(--prov-ai)",
  "-": "var(--prov-missing)",
};

/**
 * R1 brief §5.0 — a small dot form of provenance for attaching to ANY
 * displayed number inline (a ratio card's own value, say) without the
 * visual weight of `ProvenanceChip`'s bordered chip. Hover/focus reveals
 * tier, source and timestamp via the native title tooltip — no new
 * interaction pattern to build or test separately.
 */
export function ProvenanceDot({
  tier,
  source,
  asOf,
}: {
  tier: ProvenanceTier;
  source?: string | null;
  asOf?: string | null;
}) {
  const parts = [LABELS[tier]];
  if (source) parts.push(`source: ${source}`);
  if (asOf) parts.push(`as of ${asOf}`);
  return (
    <span
      aria-label={parts.join(", ")}
      title={parts.join(" — ")}
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        backgroundColor: TOKEN[tier],
        marginLeft: "var(--s1)",
        verticalAlign: "middle",
      }}
    />
  );
}
