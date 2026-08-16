import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

export interface Evidence {
  title: string;
  /** §14: "one plain sentence, no jargon" */
  whatItIs: string;
  howItIsBuilt?: ReactNode;
  inputs?: { label: string; value: ReactNode }[];
  howItCompares?: ReactNode;
  whyItMoved?: ReactNode;
  source?: { label: string; href?: string };
}

/**
 * UI & Experience Specification §14 — the explainability pattern.
 *
 * "Evidence panel slides in from the right (480px, context stays
 * visible)" and, from §6.4 and the §17 anti-pattern list, it is NEVER a
 * modal: "a modal blocks the context you are trying to compare against."
 * That is why this renders a transparent click-catcher rather than a
 * dimming scrim — the table behind stays fully readable while the panel
 * is open, which is the entire point.
 *
 * The section order is fixed by the spec: WHAT IT IS · HOW IT IS BUILT ·
 * THE INPUTS · HOW IT COMPARES · WHY IT MOVED · SOURCE. Sections with
 * nothing to show are omitted rather than rendered empty.
 */
export function EvidencePanel({ evidence, onClose }: { evidence: Evidence; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      {/* Transparent, not a dimming scrim — see the note above. */}
      <button className="evidence-scrim" aria-label="Close evidence panel" onClick={onClose} />
      <aside
        ref={panelRef}
        className="evidence-panel"
        role="region"
        aria-label={`Evidence: ${evidence.title}`}
      >
        <header className="evidence-head">
          <div>
            <span className="t-label">Evidence</span>
            <h2 style={{ marginTop: "var(--s1)" }}>{evidence.title}</h2>
          </div>
          <button ref={closeRef} onClick={onClose} aria-label="Close">
            Close
          </button>
        </header>

        <div className="evidence-body">
          <section className="evidence-section">
            <span className="t-label">What it is</span>
            <p className="prose t-body" style={{ margin: 0 }}>
              {evidence.whatItIs}
            </p>
          </section>

          {evidence.howItIsBuilt && (
            <section className="evidence-section">
              <span className="t-label">How it is built</span>
              <div className="prose t-body">{evidence.howItIsBuilt}</div>
            </section>
          )}

          {evidence.inputs && evidence.inputs.length > 0 && (
            <section className="evidence-section">
              <span className="t-label">The inputs</span>
              <table className="data-table">
                <tbody>
                  {evidence.inputs.map((input) => (
                    <tr key={input.label}>
                      <td style={{ color: "var(--ink-3)" }}>{input.label}</td>
                      <td className="right num">{input.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {evidence.howItCompares && (
            <section className="evidence-section">
              <span className="t-label">How it compares</span>
              <div className="prose t-body">{evidence.howItCompares}</div>
            </section>
          )}

          {evidence.whyItMoved && (
            <section className="evidence-section">
              <span className="t-label">Why it moved</span>
              <div className="prose t-body">{evidence.whyItMoved}</div>
            </section>
          )}

          {evidence.source && (
            <section className="evidence-section">
              <span className="t-label">Source</span>
              <div className="t-body">
                {evidence.source.href ? (
                  <a href={evidence.source.href} target="_blank" rel="noreferrer">
                    {evidence.source.label}
                  </a>
                ) : (
                  evidence.source.label
                )}
              </div>
            </section>
          )}
        </div>
      </aside>
    </>
  );
}
