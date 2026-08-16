import { useEffect, useState } from "react";
import { ApiRequestError, getMarketOverview } from "../api";
import { Delta } from "../components/Delta";
import { ErrorState, PartialNotice, SkeletonTable } from "../components/states";
import { formatIndexValue, formatMagnitude } from "../format";
import type { MarketOverview } from "../types";

/**
 * §7.1 Macro: "the regime, the variables, the project pipeline."
 *
 * The regime classifier, ARDL estimation, sector sensitivity matrix and
 * project register are all Phase 5 (§29–34) and don't exist. What DOES
 * exist and belongs on this screen is the live sector index board — real
 * data, clearly labelled for what it is — plus an honest statement of
 * what the finished screen carries.
 */
export function MacroScreen() {
  const [market, setMarket] = useState<MarketOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMarketOverview()
      .then(setMarket)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
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
        <h3>The macro engine is not built yet — Phase 5</h3>
        <p className="prose t-body">
          On the CSE this layer is worth more than the other three combined, because Sri Lankan
          equities move as a bloc with the rate cycle far more than on idiosyncratic news (§G). The
          finished screen carries the regime gauge with its probability, the
          earnings-yield-minus-364-day-T-bill spread as hero chart, a macro variable heatmap of
          z-scores, impulse-response panels, the error-correction half-life stated in plain language,
          the sector sensitivity matrix, and the national project register filtered to confirmed
          status.
        </p>
        <p className="prose t-body">
          Below is the one piece that exists today: the live S&amp;P/CSE sector index board. It is a
          passthrough, not an estimated sensitivity — it tells you what each sector did, not what it
          would do under a rate cut.
        </p>
      </div>

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
