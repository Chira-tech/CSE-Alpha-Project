import { formatPercent } from "../format";
import type { ValuedPosition } from "../types";

/**
 * "What changed / what needs a decision" — the redesign spec's §3
 * attention-first ordering, so the page leads with this rather than a
 * static table you have to read row by row. Every item here is a real
 * rollup of signals the backend already computes per position (zone,
 * thesis flags, nearest-trigger distance); nothing new is analysed and
 * nothing is a recommendation to trade.
 *
 * Renders nothing when the book is quiet — an empty strip would just be
 * noise.
 */
const NEAR_TRIGGER_PCT = 0.05;

export interface AttentionItem {
  ticker: string;
  reason: string;
}

export function attentionItems(positions: ValuedPosition[]): AttentionItem[] {
  const items: AttentionItem[] = [];
  for (const p of positions) {
    const reasons: string[] = [];
    if (p.price_ladder_zone === "exit") reasons.push("in the Exit zone");
    else if (p.price_ladder_zone === "trim") reasons.push("in the Trim zone");

    if (p.thesis_status === "weakening") {
      const flags = p.attention_flags.map((f) => f.label.toLowerCase());
      reasons.push(flags.length ? `thesis weakening (${flags.join(", ")})` : "thesis weakening");
    }

    const dist = p.nearest_trigger_distance_pct !== null ? Number(p.nearest_trigger_distance_pct) : null;
    if (
      dist !== null &&
      Math.abs(dist) <= NEAR_TRIGGER_PCT &&
      p.nearest_trigger_label &&
      p.price_ladder_zone !== "exit" &&
      p.price_ladder_zone !== "trim"
    ) {
      reasons.push(
        `${formatPercent(dist * 100)} from its ${p.nearest_trigger_label.toLowerCase()} trigger`,
      );
    }

    if (reasons.length) items.push({ ticker: p.ticker, reason: reasons.join("; ") });
  }
  return items;
}

export function NeedsAttentionStrip({
  positions,
  onOpen,
}: {
  positions: ValuedPosition[];
  onOpen: (ticker: string) => void;
}) {
  const items = attentionItems(positions);
  if (items.length === 0) return null;

  return (
    <section aria-labelledby="needs-attention-heading" className="notice notice-caution" style={{ display: "grid", gap: "var(--s2)" }}>
      <h3 id="needs-attention-heading" style={{ margin: 0 }}>
        Needs attention ({items.length})
      </h3>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--s1)" }}>
        {items.map((it) => (
          <li key={it.ticker} className="t-body">
            <button className="btn-link mono" onClick={() => onOpen(it.ticker)}>
              {it.ticker}
            </button>{" "}
            <span className="prose">— {it.reason}</span>
          </li>
        ))}
      </ul>
      <p className="t-caption muted" style={{ margin: 0 }}>
        A rollup of signals already shown per position below — not a recommendation to trade.
      </p>
    </section>
  );
}
