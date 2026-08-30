import type { PriceLadderZone } from "../types";

/**
 * "Is my book mostly healthy or mostly flashing exit?" — one glance,
 * instead of reading all N zone badges down the table. A thin horizontal
 * stacked bar over §26's five zones plus a muted "not yet valued"
 * segment, each carrying its own count and a 2px surface gap so adjacent
 * segments stay legible. Colour reuses the same `--zone-*` tokens the
 * badge and the full price ladder already use; the count label beside
 * each name means the segment is never colour-alone.
 */
const ORDER: { zone: PriceLadderZone | "none"; label: string; token: string }[] = [
  { zone: "strong_accumulate", label: "Strong accumulate", token: "var(--zone-strong-accumulate)" },
  { zone: "accumulate", label: "Accumulate", token: "var(--zone-accumulate)" },
  { zone: "fair", label: "Fair", token: "var(--zone-fair)" },
  { zone: "trim", label: "Trim", token: "var(--zone-trim)" },
  { zone: "exit", label: "Exit", token: "var(--zone-exit)" },
  { zone: "none", label: "Not yet valued", token: "var(--ink-4)" },
];

export function ZoneDistributionBar({
  zones,
}: {
  zones: (PriceLadderZone | null)[];
}) {
  const total = zones.length;
  if (total === 0) return null;

  const counts = new Map<string, number>();
  for (const z of zones) {
    const key = z ?? "none";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const present = ORDER.filter((o) => (counts.get(o.zone) ?? 0) > 0);

  return (
    <figure style={{ margin: 0 }}>
      <span className="t-label">Positions by zone</span>
      <div
        style={{
          display: "flex",
          height: 12,
          borderRadius: 2,
          overflow: "hidden",
          marginTop: "var(--s2)",
          gap: 2,
          background: "var(--surface-sunken)",
        }}
        role="img"
        aria-label={present.map((o) => `${counts.get(o.zone)} ${o.label}`).join(", ")}
      >
        {present.map((o) => (
          <div
            key={o.zone}
            style={{ flex: counts.get(o.zone), background: o.token }}
            title={`${counts.get(o.zone)} ${o.label}`}
          />
        ))}
      </div>
      <ul
        style={{
          listStyle: "none",
          margin: "var(--s2) 0 0",
          padding: 0,
          display: "flex",
          flexWrap: "wrap",
          gap: "var(--s1) var(--s4)",
          fontSize: 12,
        }}
      >
        {present.map((o) => (
          <li key={o.zone} style={{ display: "flex", alignItems: "center", gap: "var(--s2)" }}>
            <span aria-hidden style={{ width: 10, height: 10, background: o.token, borderRadius: 2 }} />
            <span style={{ color: "var(--ink-2)" }}>{o.label}</span>
            <span className="num" style={{ color: "var(--ink-3)" }}>{counts.get(o.zone)}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
