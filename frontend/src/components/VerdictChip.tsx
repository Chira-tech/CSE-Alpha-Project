/**
 * The decision engine's own call (`app.domain.decision.compute_decision`)
 * shown as a small chip — Strong Buy / Buy / Accumulate / Hold / Trim /
 * Sell / Insufficient data / Withheld.
 *
 * Deliberately NOT green/red buy-sell colouring (§1 law 6, and the API's
 * own "never a single-verdict recommendation" framing): a calm bordered
 * chip, with confidence in the tooltip. This is the real verdict carried
 * through from the valuation pass, never a label invented from the 0-100
 * composite score (§38 leaves score→action thresholds open on purpose).
 */
import { TapTip } from "./TapTip";

const ACTIONABLE = new Set(["Strong Buy", "Buy", "Trim", "Sell"]);
const NO_CALL = new Set(["Insufficient data", "Withheld"]);

export function VerdictChip({
  verdict,
  confidence,
}: {
  verdict: string;
  confidence?: string;
}) {
  const muted = NO_CALL.has(verdict);
  const chip = (
    <span
      className="chip"
      title={confidence ? `${confidence} confidence` : undefined}
      style={{
        borderColor: muted ? "var(--border-strong)" : "var(--ink-3)",
        color: muted ? "var(--ink-4)" : "var(--ink-2)",
        fontWeight: ACTIONABLE.has(verdict) ? 600 : 400,
        whiteSpace: "nowrap",
      }}
    >
      {verdict}
    </span>
  );
  return confidence ? <TapTip label={`${confidence} confidence`}>{chip}</TapTip> : chip;
}
