import type { UniverseStatusCounts } from "../types";
import { formatAgo } from "../format";

/**
 * Homepage redesign §6: "The trust bar comes first. A thin strip, not a
 * card. Everything below it is worthless if it's red, so it's the first
 * thing on the page — but it's one line, because on a good day it
 * deserves one line."
 *
 * One row per security from `/data-health`'s `universe_status`, split by
 * the formal 4-state status (clean / provisional / quarantined /
 * unresolved). The bar is a thin stacked proportion; every segment
 * carries its own count beside a word, so meaning never rests on colour
 * alone (§8). Colour follows the existing §16 tokens — `--caution` is
 * the reserved data-quality amber (§7: "Blocked is amber, not red"),
 * `--neg` marks the genuinely distrusted quarantine set, everything
 * unresolved is muted ink, and the clean majority is a calm brand tone
 * rather than a "gain" green.
 *
 * `computedAt` / `stale` describe the run the scores below were built
 * from — a stale strip says so in amber rather than implying a
 * freshness it can't back up.
 */
const SEGMENTS: {
  key: keyof Omit<UniverseStatusCounts, "total">;
  label: string;
  token: string;
}[] = [
  { key: "clean", label: "clean", token: "var(--brand-300)" },
  { key: "provisional", label: "provisional", token: "var(--caution)" },
  { key: "quarantined", label: "quarantined", token: "var(--neg)" },
  { key: "unresolved", label: "unresolved", token: "var(--ink-4)" },
];

export function TrustBar({
  status,
  computedAt,
  stale,
}: {
  status: UniverseStatusCounts;
  computedAt?: string | null;
  stale?: boolean;
}) {
  const total = status.total || 1;
  const present = SEGMENTS.filter((s) => status[s.key] > 0);

  return (
    <div
      className="trust-bar"
      role="group"
      aria-label={`Universe data quality: ${present
        .map((s) => `${status[s.key]} ${s.label}`)
        .join(", ")}`}
    >
      <div
        className="trust-bar-track"
        aria-hidden="true"
        style={{ display: "flex", gap: 2, height: 6 }}
      >
        {present.map((s) => (
          <span
            key={s.key}
            title={`${status[s.key]} ${s.label}`}
            style={{ flex: status[s.key] / total, background: s.token, borderRadius: 1 }}
          />
        ))}
      </div>

      <div className="trust-bar-legend">
        {SEGMENTS.map((s) => (
          <span key={s.key} className="trust-bar-item">
            <span aria-hidden style={{ width: 8, height: 8, borderRadius: 2, background: s.token }} />
            <span className="num" style={{ fontWeight: 600 }}>
              {status[s.key]}
            </span>
            <span style={{ color: "var(--ink-3)" }}>{s.label}</span>
          </span>
        ))}
        {computedAt !== undefined && (
          <span
            className="trust-bar-item"
            style={{ marginLeft: "auto", color: stale ? "var(--caution)" : "var(--ink-3)" }}
          >
            {computedAt
              ? `scores from a run ${formatAgo(computedAt)}${stale ? " — market has moved since" : ""}`
              : "scores computed live — no scheduled run yet"}
          </span>
        )}
      </div>
    </div>
  );
}
