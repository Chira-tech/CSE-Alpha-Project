export type Verdict = "strong" | "adequate" | "weak" | "no_data";

const LABEL: Record<Verdict, string> = {
  strong: "Strong",
  adequate: "Adequate",
  weak: "Weak",
  no_data: "No data",
};

// Calm palette only — never red/green market-movement colouring (§1 law
// 6). "Weak" uses caution (amber), never `--neg`, which this app
// reserves for a real negative number, not a quality judgement.
const TOKEN: Record<Verdict, string> = {
  strong: "var(--pos-strong)",
  adequate: "var(--brand-300)",
  weak: "var(--caution)",
  no_data: "var(--ink-4)",
};

const GLYPH: Record<Verdict, string> = {
  strong: "●",
  adequate: "◐",
  weak: "○",
  no_data: "—",
};

/**
 * R1 brief §5.0 — a good/neutral/poor judgement on a metric, four
 * states. Colour is never the only carrier of meaning: label text and a
 * glyph both accompany it, same discipline `Delta`/`ZoneChip` already
 * established for direction.
 */
export function VerdictPill({ verdict, title }: { verdict: Verdict; title?: string }) {
  return (
    <span className="chip" style={{ borderColor: TOKEN[verdict], color: TOKEN[verdict] }} title={title}>
      <span aria-hidden="true">{GLYPH[verdict]}</span> {LABEL[verdict]}
    </span>
  );
}

/**
 * A real, disclosed threshold mapping — never invented per call site.
 * Callers needing a different mapping for a different metric shape pass
 * their own `Verdict` directly instead of using this helper.
 */
export function verdictFromPercentile(percentile: number | null): Verdict {
  if (percentile === null) return "no_data";
  if (percentile >= 70) return "strong";
  if (percentile >= 40) return "adequate";
  return "weak";
}
