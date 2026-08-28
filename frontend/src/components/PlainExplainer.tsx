import type { ReactNode } from "react";

/**
 * R1 brief §5.0 — "one-line interpretation under a metric... content
 * authored per metric, not generated at runtime." This component is
 * deliberately dumb: it renders a headline conclusion plus supporting
 * body text a CALLER already chose from real, authored copy for real
 * thresholds (see e.g. `TodayScreen`'s own earnings-yield states) — it
 * never invents a sentence from a number itself, which is exactly the
 * class of "confident, precise, fictional" text this project's own
 * copy rules (§5.0) warn against.
 */
export function PlainExplainer({ headline, body }: { headline: string; body: ReactNode }) {
  return (
    <div className="stack-tight" style={{ marginTop: "var(--s2)" }}>
      <p className="prose t-body" style={{ margin: 0, fontWeight: 600 }}>
        {headline}
      </p>
      <p className="prose t-body" style={{ margin: 0 }}>
        {body}
      </p>
    </div>
  );
}
