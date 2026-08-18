import { useEffect, useState } from "react";
import { ApiRequestError, getIndexHistory, getMarketOverview, getSectorSensitivity, getSpread } from "../api";
import { Delta } from "../components/Delta";
import { IndexHistoryChart } from "../components/IndexHistoryChart";
import { SectorSensitivityMatrix } from "../components/SectorSensitivityMatrix";
import { SpreadHero } from "../components/SpreadHero";
import { ErrorState, PartialNotice, SkeletonCard, SkeletonTable } from "../components/states";
import { formatIndexValue, formatMagnitude } from "../format";
import type { IndexHistory, MarketOverview, SectorSensitivity, Spread } from "../types";

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
 * STILL NOT ON THIS SCREEN: the regime gauge (the classifier exists on
 * the backend but hasn't been validated against real historical Sri
 * Lankan regime periods — this system's own real macro series don't yet
 * span one), the macro variable heatmap, the causality/impulse-response
 * panels, and the national project register. Named here rather than
 * silently omitted.
 */
export function MacroScreen() {
  const [market, setMarket] = useState<MarketOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState<IndexHistory | null>(null);
  const [spread, setSpread] = useState<Spread | null>(null);
  const [sensitivity, setSensitivity] = useState<SectorSensitivity | null>(null);
  const [sensitivityError, setSensitivityError] = useState<string | null>(null);

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
          hero spread and sector sensitivity matrix below are real, live estimates. Still missing:
          the regime gauge (the classifier itself exists, but hasn't been validated against a real
          historical Sri Lankan regime — this system's own macro series aren't deep enough yet), a
          macro variable heatmap, the causality/impulse-response panels, and the national project
          register.
        </p>
      </div>

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
          <SectorSensitivityMatrix data={sensitivity} />
        ) : (
          <SkeletonTable rows={10} columns={5} />
        )}
      </section>

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
                  S&amp;P/CSE industry-group indices, live from cse.lk.
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
                        {s.name}
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
