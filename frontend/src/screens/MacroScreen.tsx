import { useEffect, useState } from "react";
import {
  ApiRequestError,
  getIndexHistory,
  getMarketOverview,
  getRegimeGauge,
  getSectorSensitivity,
  getSpread,
} from "../api";
import { Delta } from "../components/Delta";
import { IndexHistoryChart } from "../components/IndexHistoryChart";
import { SectorDrilldownPanel } from "../components/SectorDrilldownPanel";
import { RegimeGaugePanel } from "../components/RegimeGaugePanel";
import { SectorSensitivityMatrix } from "../components/SectorSensitivityMatrix";
import { SpreadHero } from "../components/SpreadHero";
import { ErrorState, PartialNotice, SkeletonCard, SkeletonTable } from "../components/states";
import { formatIndexValue, formatMagnitude } from "../format";
import type {
  IndexHistory,
  MarketOverview,
  RegimeGauge,
  SectorSensitivity,
  Spread,
} from "../types";

/**
 * §7.1 Macro: "the regime, the variables, the project pipeline."
 *
 * Phase 5 (§29–34) is now real on the backend: the §29 hero spread, unit
 * root / cointegration testing, Johansen/VECM and VAR-in-differences
 * estimation, impulse-response/FEVD and Toda-Yamamoto causality, an
 * event study around CBSL policy-rate changes, and the §33 sector
 * sensitivity matrix. This screen surfaces the two pieces the spec
 * names as the centre of the layer — the hero spread and the sensitivity
 * matrix — plus the live sector index board that was already here.
 *
 * THE REGIME GAUGE IS NOW ON THIS SCREEN (29 Aug 2026) — the live read,
 * the two independent sub-reads behind it, what it is already doing to
 * every fair value, §30 step 2's error-correction half-life and the §33
 * tilts that are significant right now. Two pieces of it are still
 * genuinely absent and say so on screen: a recommended gross exposure
 * (§31 names exposure-capping but gives no number, and no
 * portfolio-sizing layer exists for one to act on) and validation
 * against a real historical Sri Lankan regime.
 *
 * STILL NOT ON THIS SCREEN: the macro variable heatmap, the
 * causality/impulse-response panels, and the national project register.
 * Named here rather than
 * silently omitted.
 */
export function MacroScreen({ onOpen }: { onOpen: (ticker: string) => void }) {
  const [market, setMarket] = useState<MarketOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState<IndexHistory | null>(null);
  const [spread, setSpread] = useState<Spread | null>(null);
  const [sensitivity, setSensitivity] = useState<SectorSensitivity | null>(null);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);
  const [regime, setRegime] = useState<RegimeGauge | null>(null);
  const [regimeError, setRegimeError] = useState<string | null>(null);
  // R1 T4.6.4 — which sector's drill-down panel is open, if any.
  const [drilldownSector, setDrilldownSector] = useState<string | null>(null);

  useEffect(() => {
    getMarketOverview()
      .then(setMarket)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
    // Stored history, so it survives a live-feed outage independently of
    // the sector board above — a failure there must not blank this.
    getIndexHistory()
      .then(setIndex)
      .catch(() => setIndex(null));
    getSpread()
      .then(setSpread)
      .catch(() => setSpread(null));
    getSectorSensitivity()
      .then(setSensitivity)
      .catch((e) => setSensitivityError(e instanceof ApiRequestError ? e.message : String(e)));
    // Genuinely slow (a real Markov fit + an ARDL bounds test + the whole
    // §33 matrix), so it loads alongside everything else rather than
    // gating the screen on it.
    getRegimeGauge()
      .then(setRegime)
      .catch((e: unknown) => setRegimeError(e instanceof ApiRequestError ? e.message : String(e)));
  }, []);

  // The feed includes the all-share index as a sector row; showing it in
  // a table of sectors would double-count it against the hero above.
  const sectors = market?.sectors.filter((s) => s.symbol !== "ASI") ?? [];

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Macro</h1>
        <p className="prose">The regime, the variables, the project pipeline.</p>
      </header>

      <div className="notice notice-neutral">
        <h3>What's real on this screen, and what's still missing</h3>
        <p className="prose t-body">
          On the CSE this layer is worth more than the other three combined, because Sri Lankan
          equities move as a bloc with the rate cycle far more than on idiosyncratic news (§G). The
          hero spread, the regime gauge and the sector sensitivity matrix below are all real, live
          estimates. Still missing: a recommended gross exposure (§31 names exposure-capping but
          gives no number for it, and there is no portfolio-sizing layer for one to act on),
          validation of the classifier against a real historical Sri Lankan regime (this system's
          own macro series aren't deep enough yet), a macro variable heatmap, the
          causality/impulse-response panels, and the national project register.
        </p>
      </div>

      <section aria-labelledby="regime-heading" className="stack-tight">
        <h2 id="regime-heading">Regime gauge (§31)</h2>
        {regimeError && (
          <ErrorState
            whatFailed={`The regime gauge could not be loaded: ${regimeError}`}
            whatItAffects="This section only."
            whatStillWorks="The hero spread, the sensitivity matrix and the sector board below are loaded independently and are unaffected."
            whatHappensNext="Reload the screen once the backend is reachable — nothing is cached, so a retry re-fits the model."
          />
        )}
        {!regime && !regimeError && <p className="t-body">Fitting the regime model…</p>}
        {regime && <RegimeGaugePanel gauge={regime} />}
      </section>

      <section aria-labelledby="spread-heading" className="stack-tight">
        <h2 id="spread-heading">The hero spread (§29)</h2>
        {spread ? <SpreadHero spread={spread} /> : <SkeletonCard lines={4} />}
      </section>

      <section aria-labelledby="sensitivity-heading" className="stack-tight">
        <h2 id="sensitivity-heading">Sector sensitivity matrix (§33)</h2>
        {sensitivityError ? (
          <ErrorState
            whatFailed="The sector sensitivity matrix could not be loaded"
            whatItAffects="This section only."
            whatStillWorks="The hero spread and sector index board below both read independently."
            whatHappensNext={`Underlying error: ${sensitivityError}`}
          />
        ) : sensitivity ? (
          <SectorSensitivityMatrix data={sensitivity} onSelectSector={setDrilldownSector} />
        ) : (
          <SkeletonTable rows={10} columns={5} />
        )}
      </section>

      {drilldownSector && (
        <SectorDrilldownPanel
          sector={drilldownSector}
          sensitivityRow={sensitivity?.rows.find((r) => r.sector === drilldownSector)}
          onClose={() => setDrilldownSector(null)}
          onOpenCompany={onOpen}
        />
      )}

      {index && index.points.length > 1 && (
        <section aria-labelledby="aspi-history-heading" className="stack-tight">
          <h2 id="aspi-history-heading">ASPI, last year</h2>
          <div className="card">
            <IndexHistoryChart history={index} />
          </div>
        </section>
      )}

      <section aria-labelledby="sectors-heading" className="stack-tight">
        <h2 id="sectors-heading">Sector indices</h2>

        {error ? (
          <ErrorState
            whatFailed="The sector index board could not be loaded"
            whatItAffects="This screen only."
            whatStillWorks="Companies, Data health and the confirm queues, all of which read the local database rather than the live feed."
            whatHappensNext={
              <>
                Check the API is running at <span className="code-hint">http://localhost:8000</span>{" "}
                and that it can reach cse.lk, then reload. Underlying error: {error}
              </>
            }
          />
        ) : !market ? (
          <SkeletonTable rows={8} columns={4} />
        ) : (
          <>
            {market.unavailable.length > 0 && <PartialNotice sections={market.unavailable} />}
            <div className="table-wrap table-scroll">
              <table className="data-table">
                <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
                  S&amp;P/CSE industry-group indices, live from cse.lk. Click a sector name for its
                  real market-share treemap and macro sensitivities (same drill-down as the matrix
                  above).
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Sector</th>
                    <th scope="col" className="right">Index</th>
                    <th scope="col" className="right">Change</th>
                    <th scope="col" className="right">Turnover today (LKR)</th>
                  </tr>
                </thead>
                <tbody>
                  {sectors.map((s) => (
                    <tr key={s.name}>
                      <th scope="row" style={{ fontWeight: 500, background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, color: "var(--ink-1)" }}>
                        <button className="btn-link" onClick={() => setDrilldownSector(s.name)}>
                          {s.name}
                        </button>
                      </th>
                      <td className="right num">{formatIndexValue(s.index_value)}</td>
                      <td className="right">
                        <Delta percentage={s.percentage} />
                      </td>
                      <td className="right num">{formatMagnitude(s.turnover_today)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="t-caption">
              Fetched {new Date(market.fetched_at).toLocaleTimeString()}
              {market.cached ? " (cached)" : ""}. Not stored, not point-in-time — no model reads
              these figures.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
