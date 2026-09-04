import { useEffect, useState } from "react";
import {
  ApiRequestError,
  getIndexHistory,
  getMarketOverview,
  getRegimeGauge,
  getSectorSensitivity,
  getSpread,
} from "../api";
import { IndexHistoryChart } from "../components/IndexHistoryChart";
import { SectorDrilldownPanel } from "../components/SectorDrilldownPanel";
import { RegimeGaugePanel } from "../components/RegimeGaugePanel";
import { SectorPerformanceBars } from "../components/SectorPerformanceBars";
import { SectorSensitivityMatrix } from "../components/SectorSensitivityMatrix";
import { SpreadHero } from "../components/SpreadHero";
import { ErrorState, PartialNotice, SkeletonCard, SkeletonTable } from "../components/states";
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
 * Redesigned per `docs/macro-page-redesign-spec_1.md` (4 Sep 2026) —
 * same principles as the Portfolio, Company and Data Health redesigns:
 * the answer (regime call + hero spread) leads the page, a single amber
 * blocker strip carries every disclosed gap ABOVE the numbers it
 * qualifies instead of after them, and every chart-shaped number
 * (a 3-way probability, a signed spread over time, a sector-by-shock
 * matrix, a ranked list of ~20 sectors) gets an actual chart instead of
 * text lines or a table.
 *
 * Phase 5 (§29–34) is the real backend behind all of it: the §29 hero
 * spread, unit root / cointegration testing, Johansen/VECM and
 * VAR-in-differences estimation, impulse-response/FEVD and
 * Toda-Yamamoto causality, an event study around CBSL policy-rate
 * changes, and the §33 sector sensitivity matrix.
 *
 * The ASPI chart is regime-shaded (spec §8 build item 8) using
 * `RegimeGauge.history` — the Markov fit's own per-day path, which was
 * already computed every call and simply discarded past the last row
 * until 4 Sep 2026, so no new data source or persistence was needed to
 * build this. It is the statistical half only, not the 50/50 blend the
 * current-day call uses — `IndexHistoryChart`'s own caption says so.
 *
 * STILL NOT ON THIS SCREEN, named rather than silently omitted: a
 * recommended gross exposure (§31 names exposure-capping but gives no
 * number, and there is no portfolio-sizing layer for one to act on),
 * validation of the classifier against a real historical Sri Lankan
 * regime, the macro variable heatmap, the causality/impulse-response
 * panels, and the national project register.
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
        <p className="prose">The regime, the variables, and what still isn't proven.</p>
      </header>

      <BlockerStrip regime={regime} sensitivity={sensitivity} spread={spread} />

      <div className="split-row">
        <section aria-labelledby="regime-heading" className="stack-tight">
          <h2 id="regime-heading" className="visually-hidden">Current regime</h2>
          {regimeError && (
            <ErrorState
              whatFailed={`The regime gauge could not be loaded: ${regimeError}`}
              whatItAffects="This card only."
              whatStillWorks="The hero spread, the sensitivity matrix and the sector board below are loaded independently and are unaffected."
              whatHappensNext="Reload the screen once the backend is reachable — nothing is cached, so a retry re-fits the model."
            />
          )}
          {!regime && !regimeError && <SkeletonCard lines={4} />}
          {regime && <RegimeGaugePanel gauge={regime} />}
        </section>

        <section aria-labelledby="spread-heading" className="stack-tight">
          <h2 id="spread-heading" className="visually-hidden">The hero spread</h2>
          {spread ? <SpreadHero spread={spread} /> : <SkeletonCard lines={4} />}
        </section>
      </div>

      {regime && <RegimeConsequenceBand regime={regime} />}

      <section aria-labelledby="sensitivity-heading" className="stack-tight">
        <h2 id="sensitivity-heading">Sector sensitivity — where the regime actually bites</h2>
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

      <div className="split-row">
        <section aria-labelledby="sectors-heading" className="stack-tight">
          <h2 id="sectors-heading">Sector performance today</h2>
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
              <SectorPerformanceBars sectors={sectors} onSelectSector={setDrilldownSector} />
              <p className="t-caption">
                Fetched {new Date(market.fetched_at).toLocaleTimeString()}
                {market.cached ? " (cached)" : ""}. Not stored, not point-in-time — no model reads
                these figures. Click a sector for its real market-share treemap and macro
                sensitivities (same drill-down as the matrix above).
              </p>
            </>
          )}
        </section>

        {index && index.points.length > 1 && (
          <section aria-labelledby="aspi-history-heading" className="stack-tight">
            <h2 id="aspi-history-heading">ASPI, last 12 months</h2>
            <div className="card">
              <IndexHistoryChart history={index} regimeHistory={regime?.history} />
            </div>
          </section>
        )}
      </div>

      <details className="card-sunken">
        <summary className="t-data" style={{ cursor: "pointer" }}>
          How this page is computed
        </summary>
        <p className="prose t-body" style={{ marginTop: "var(--s3)" }}>
          On the CSE this layer is worth more than the other three combined, because Sri Lankan
          equities move as a bloc with the rate cycle far more than on idiosyncratic news (§G). The
          hero spread, the regime gauge and the sector sensitivity matrix above are all real, live
          estimates — nothing on this page is illustrative or hard-coded. The regime read blends two
          independent models (a Markov-switching fit on ASPI returns and a rule-based macro
          composite); the sensitivity matrix is a real OLS regression per sector/shock pair, shown
          only once at least 20 real overlapping trading-day observations exist.
        </p>
      </details>
    </div>
  );
}

/**
 * Macro page redesign spec §3/§5 — every disclosed gap that qualifies
 * trust in the numbers above, promoted to a single strip at the very top
 * of the page instead of scattered after the sections they qualify.
 * Amber, never red (`.notice-caution` — data-quality state, not a sell
 * signal), and collapses to a quiet one-line confirmation when nothing
 * is outstanding rather than just disappearing, so "0 open validations"
 * is itself a visible, calm signal.
 */
function BlockerStrip({
  regime,
  sensitivity,
  spread,
}: {
  regime: RegimeGauge | null;
  sensitivity: SectorSensitivity | null;
  spread: Spread | null;
}) {
  const items: string[] = [];
  if (regime) items.push(...regime.not_built);
  if (sensitivity) items.push(...sensitivity.warnings);
  if (spread && !spread.available) items.push(...spread.missing);

  // Still loading everything — say nothing yet rather than a premature
  // "all clear" that a moment later turns out to have gaps.
  if (!regime && !sensitivity && !spread) return null;

  if (items.length === 0) {
    return (
      <p className="t-caption" style={{ color: "var(--pos-strong)", margin: 0 }}>
        0 open validations — every gap this page knows how to check for is closed.
      </p>
    );
  }

  return (
    <section aria-labelledby="blockers-heading" className="notice notice-caution">
      <h3 id="blockers-heading" style={{ margin: 0 }}>
        {items.length} not yet validated
      </h3>
      <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "var(--s5)" }}>
        {items.map((it) => (
          <li key={it} className="t-body">
            {it}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * "What this regime is already doing to every allocation" — kept
 * visible (spec §5: "the one place the page currently states a real
 * consequence, even if it's 0.0% today"), just moved to a compact
 * full-width band under the hero row instead of buried inside the
 * regime card.
 */
function RegimeConsequenceBand({ regime }: { regime: RegimeGauge }) {
  const pct = (v: string | null) => (v === null ? "—" : `${(Number(v) * 100).toFixed(1)}%`);
  return (
    <section aria-labelledby="consequence-heading" className="card-sunken">
      <h3 id="consequence-heading" className="t-label" style={{ margin: 0 }}>
        What this regime is doing to your numbers right now
      </h3>
      <div className="stat-grid" style={{ marginTop: "var(--s3)" }}>
        <div>
          <p className="t-caption muted" style={{ margin: 0 }}>Margin of safety widened</p>
          <p className="stat-value" style={{ margin: 0 }}>{pct(regime.consequence.margin_of_safety_add_pct)}</p>
        </div>
        <div>
          <p className="t-caption muted" style={{ margin: 0 }}>Added to equity risk premium</p>
          <p className="stat-value" style={{ margin: 0 }}>{pct(regime.consequence.erp_add_pct)}</p>
        </div>
      </div>
      <p className="prose t-caption" style={{ marginTop: "var(--s3)", marginBottom: 0 }}>
        {regime.consequence.note}
      </p>
    </section>
  );
}
