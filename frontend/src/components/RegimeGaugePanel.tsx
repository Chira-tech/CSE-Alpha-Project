import type { RegimeGauge } from "../types";

/**
 * §31's regime gauge.
 *
 * Shows the live read, the TWO INDEPENDENT sub-reads it is blended from
 * (a real Markov switching fit on ASPI returns, and a rule-based
 * composite over §31's own signature table), what the regime is ALREADY
 * doing to every fair value in the system, §30 step 2's error-correction
 * half-life, and the §33 sector tilts that are statistically significant
 * right now.
 *
 * Two things are deliberately NOT here, and say so on screen rather than
 * being approximated: a recommended gross exposure (§31 names
 * exposure-capping but gives no number, and there is no portfolio-sizing
 * layer for one to act on) and validation against a real historical Sri
 * Lankan regime (the classifier is validated against a synthetic
 * two-regime series; the CBSL history here is not deep enough to reach
 * the 2022 sovereign default).
 */

const LABEL_TEXT: Record<string, string> = {
  risk_on: "Risk-On",
  transition: "Transition",
  risk_off: "Risk-Off",
};

function pct(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

export function RegimeGaugePanel({ gauge }: { gauge: RegimeGauge }) {
  const label = gauge.label;
  const ordered = ["risk_on", "transition", "risk_off"];

  return (
    <div className="stack-tight">
      <div>
        <p className="t-label">Current read</p>
        <p className="t-display" style={{ marginTop: "var(--s1)" }}>
          {label ? LABEL_TEXT[label] ?? label : "Not computable yet"}
        </p>
        <p className="prose t-body">{gauge.note}</p>
      </div>

      {Object.keys(gauge.probabilities).length > 0 && (
        <div>
          <p className="t-label">Blended probability</p>
          <table>
            <caption className="visually-hidden">
              Probability assigned to each regime by the blended read
            </caption>
            <thead>
              <tr>
                <th scope="col">Regime</th>
                <th scope="col" className="num">
                  Probability
                </th>
              </tr>
            </thead>
            <tbody>
              {ordered
                .filter((k) => gauge.probabilities[k] !== undefined)
                .map((k) => (
                  <tr key={k}>
                    <th scope="row">{LABEL_TEXT[k] ?? k}</th>
                    <td className="num">{pct(gauge.probabilities[k])}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {gauge.sub_reads.length > 0 && (
        <div>
          <p className="t-label">The two independent reads behind it</p>
          <ul className="stack-tight">
            {gauge.sub_reads.map((r) => (
              <li key={r.kind}>
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
        <p className="t-label">What this regime is already doing to every valuation</p>
        <table>
          <caption className="visually-hidden">
            Live regime consequences applied across the system
          </caption>
          <thead>
            <tr>
              <th scope="col">Consequence</th>
              <th scope="col" className="num">
                Applied now
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Margin of safety widened by (§25)</th>
              <td className="num">{pct(gauge.consequence.margin_of_safety_add_pct)}</td>
            </tr>
            <tr>
              <th scope="row">Added to the equity risk premium (§17.2)</th>
              <td className="num">{pct(gauge.consequence.erp_add_pct)}</td>
            </tr>
          </tbody>
        </table>
        <p className="prose t-body">{gauge.consequence.note}</p>
      </div>

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
                <th scope="col" className="num">
                  p-value
                </th>
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

      <div className="notice notice-neutral">
        <h3>Still missing from this gauge</h3>
        <ul className="stack-tight">
          {gauge.not_built.map((n) => (
            <li key={n} className="t-body">
              {n}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
