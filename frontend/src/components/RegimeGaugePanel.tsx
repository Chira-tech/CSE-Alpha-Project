import { RegimeProbabilityBar } from "./RegimeProbabilityBar";
import type { RegimeGauge } from "../types";

/**
 * §31's regime gauge, redesigned per `docs/macro-page-redesign-spec_1.md`
 * — the answer (current read + blended probability) leads; the working
 * behind it (the two independent sub-reads, the error-correction
 * half-life, which sector tilts are significant right now) is one click
 * away in a `<details>`, not stacked in the first screen's worth of
 * content.
 *
 * `consequence` (what the regime is already doing to every fair value)
 * and `not_built` (the gauge's own disclosed gaps) are deliberately NOT
 * rendered here any more — `MacroScreen` reads them directly so they can
 * sit in the page-level consequence band and blocker strip respectively,
 * instead of being buried inside this card.
 */

const LABEL_TEXT: Record<string, string> = {
  risk_on: "Risk-On",
  transition: "Transition",
  risk_off: "Risk-Off",
};

export function RegimeGaugePanel({ gauge }: { gauge: RegimeGauge }) {
  const label = gauge.label;
  const hasDetail = gauge.sub_reads.length > 0 || gauge.half_life_note || gauge.sector_tilts.length > 0;

  return (
    <div className="card stack-tight">
      <span className="t-label">Current regime</span>
      <p className="t-display" style={{ margin: 0 }}>
        {label ? LABEL_TEXT[label] ?? label : "Not computable yet"}
      </p>

      <RegimeProbabilityBar gauge={gauge} />

      <p className="prose t-body" style={{ margin: 0 }}>
        {gauge.note}
      </p>

      {hasDetail && (
        <details style={{ marginTop: "var(--s2)" }}>
          <summary className="t-caption" style={{ cursor: "pointer" }}>
            Details — the two independent reads, sector tilts, half-life
          </summary>
          <div className="stack-tight" style={{ marginTop: "var(--s3)" }}>
            {gauge.sub_reads.length > 0 && (
              <div>
                <p className="t-label">The two independent reads behind it</p>
                <ul className="stack-tight">
                  {gauge.sub_reads.map((r) => (
                    <li key={r.kind} className="t-body">
                      <strong>{r.kind === "markov" ? "Markov switching" : "Macro composite"}</strong>
                      {r.label ? ` — ${LABEL_TEXT[r.label] ?? r.label}` : ""}
                      <br />
                      <span className="t-body">{r.detail}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <p className="t-label">Error-correction half-life (§30 step 2)</p>
              <p className="t-body">
                {gauge.half_life_periods
                  ? `${Number(gauge.half_life_periods).toFixed(1)} periods`
                  : "Not estimable from current data"}
              </p>
              <p className="prose t-body">{gauge.half_life_note}</p>
            </div>

            <div>
              <p className="t-label">Sector tilts (§33)</p>
              <p className="prose t-body">{gauge.sector_tilt_note}</p>
              {gauge.sector_tilts.length > 0 && (
                <table>
                  <caption className="visually-hidden">
                    Statistically significant sector sensitivities to macro shocks
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Sector</th>
                      <th scope="col">Shock</th>
                      <th scope="col">Direction</th>
                      <th scope="col" className="num">p-value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gauge.sector_tilts.map((t) => (
                      <tr key={`${t.sector}-${t.shock}`}>
                        <th scope="row">{t.sector}</th>
                        <td>{t.shock}</td>
                        <td>{t.direction === "positive" ? "Benefits" : "Hurt by"}</td>
                        <td className="num">{Number(t.p_value).toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </details>
      )}
    </div>
  );
}
