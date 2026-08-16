import type { ReactNode } from "react";

/**
 * UI & Experience Specification §15.1 — every component specifies six
 * states. These are the shared implementations so a screen can't quietly
 * invent a worse one.
 */

/**
 * Loading. §15.1: "Skeleton at the final layout's dimensions. Never a
 * spinner over a collapsing layout." Callers pass the shape they're
 * about to render, so the page doesn't jump when data lands.
 */
export function SkeletonTable({ rows = 6, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <div className="table-wrap" aria-busy="true" aria-live="polite" aria-label="Loading">
      <table className="data-table">
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r}>
              {Array.from({ length: columns }).map((__, c) => (
                <td key={c}>
                  <div className="skeleton skeleton-line" style={{ width: c === 0 ? "60%" : "80%" }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card" aria-busy="true" aria-live="polite" aria-label="Loading">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton skeleton-line"
          style={{ width: i === 0 ? "40%" : "70%", height: i === 0 ? 34 : 13 }}
        />
      ))}
    </div>
  );
}

/**
 * Empty. §15.1: "Says what would fill it and what to do."
 */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="notice notice-neutral">
      <h3>{title}</h3>
      {children && <div className="prose t-body">{children}</div>}
    </div>
  );
}

/**
 * Error. §15.1 is specific about the four things an error must say:
 * "What failed, what it affects, what still works, what happens next.
 * Never a raw stack trace, never a bare 'something went wrong.'"
 * The props are named after those four so an incomplete error state
 * doesn't type-check.
 */
export function ErrorState({
  whatFailed,
  whatItAffects,
  whatStillWorks,
  whatHappensNext,
}: {
  whatFailed: string;
  whatItAffects: string;
  whatStillWorks: string;
  whatHappensNext: ReactNode;
}) {
  return (
    <div className="notice notice-caution" role="alert">
      <h3>{whatFailed}</h3>
      <dl>
        <dt>Affects</dt>
        <dd>{whatItAffects}</dd>
        <dt>Still works</dt>
        <dd>{whatStillWorks}</dd>
        <dt>Next</dt>
        <dd>{whatHappensNext}</dd>
      </dl>
    </div>
  );
}

/**
 * Partial. §15.1: "Renders what exists, marks what does not."
 */
export function PartialNotice({ sections }: { sections: { section: string; reason: string }[] }) {
  if (sections.length === 0) return null;
  return (
    <div className="notice notice-caution" role="status">
      <h3>Some of this screen could not be loaded</h3>
      <dl>
        {sections.map((s) => (
          <div key={s.section} style={{ display: "contents" }}>
            <dt>{s.section}</dt>
            <dd>{s.reason}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/**
 * Stale. §5.4/§15.1: ochre timestamp stating the age plainly. Stale data
 * is never silently rendered as current.
 */
export function AsOf({ label, stale }: { label: string; stale?: boolean }) {
  return <span className={stale ? "as-of as-of-stale" : "as-of"}>{label}</span>;
}

/**
 * Quarantined. §15.1: ticker-level, full-width notice, model outputs
 * suppressed rather than shown stale.
 */
export function QuarantineNotice({ ticker }: { ticker: string }) {
  return (
    <div className="notice notice-caution" role="alert">
      <h3>{ticker} is quarantined</h3>
      <p className="prose t-body">
        An unresolved data-quality alert is open against this ticker. Master Spec §7 requires it be
        excluded from every model until a human resolves the underlying issue, so any figures below
        are shown for inspection only and no model output is published for this name.
      </p>
    </div>
  );
}
