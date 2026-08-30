import { useEffect, useState } from "react";
import { ApiRequestError, downloadBackup, downloadWorkbook, getDataHealth } from "../api";
import { AsOf, EmptyState, ErrorState, SkeletonCard } from "../components/states";
import { downloadBlob } from "../csv";
import { onDataRefreshed } from "../dataRefresh";
import { formatInteger, UNAVAILABLE } from "../format";
import type { DataHealth } from "../types";

export function DataHealthScreen({ onOpenReview }: { onOpenReview: () => void }) {
  const [data, setData] = useState<DataHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [workbookBusy, setWorkbookBusy] = useState(false);
  const [workbookError, setWorkbookError] = useState<string | null>(null);
  const [workbookNotice, setWorkbookNotice] = useState<string | null>(null);
  const [backupBusy, setBackupBusy] = useState(false);
  const [backupError, setBackupError] = useState<string | null>(null);
  const [backupNotice, setBackupNotice] = useState<string | null>(null);

  async function handleDownloadWorkbook() {
    setWorkbookBusy(true);
    setWorkbookError(null);
    setWorkbookNotice(null);
    try {
      const { blob, filename } = await downloadWorkbook();
      downloadBlob(filename, blob);
      setWorkbookNotice(`Downloaded ${filename} at ${new Date().toLocaleTimeString()}.`);
    } catch (e) {
      setWorkbookError(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setWorkbookBusy(false);
    }
  }

  async function handleDownloadBackup() {
    setBackupBusy(true);
    setBackupError(null);
    setBackupNotice(null);
    try {
      const { blob, filename } = await downloadBackup();
      downloadBlob(filename, blob);
      setBackupNotice(`Downloaded ${filename} at ${new Date().toLocaleTimeString()}.`);
    } catch (e) {
      setBackupError(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setBackupBusy(false);
    }
  }

  useEffect(() => {
    function load() {
      getDataHealth()
        .then(setData)
        .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
    }
    load();
    // P1.1: a completed "Run Capture" job just wrote real rows this
    // screen's own counts depend on — refetch rather than wait for the
    // human to happen to reload.
    return onDataRefreshed(load);
  }, []);

  if (error) {
    return (
      <div className="route stack">
        <header className="screen-head">
          <h1>Data health</h1>
        </header>
        <ErrorState
          whatFailed="Data health could not be loaded"
          whatItAffects="This screen only."
          whatStillWorks="Today and Macro read the live CSE feed and are unaffected by the local database."
          whatHappensNext={
            <>
              Check the API is running at <span className="code-hint">http://localhost:8000</span>,
              then reload. Underlying error: {error}
            </>
          }
        />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="route stack">
        <header className="screen-head">
          <h1>Data health</h1>
        </header>
        <SkeletonCard lines={4} />
      </div>
    );
  }

  // §50's monitor is ">36h since last successful ingest"; expressed in
  // days here because the store is daily EOD, and allowing for weekends.
  const stale = data.price_feed_age_days !== null && data.price_feed_age_days > 2;
  const pending = data.corporate_actions_pending + data.fundamentals_pending_confirmation;
  const ui = data.universe_integrity;

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Data health</h1>
        <p className="prose">
          Freshness, reconciliation and the confirm queue. The spec gives this a real screen rather
          than an admin afterthought because it is where data quality is actually maintained.
        </p>
      </header>

      <section aria-labelledby="coverage-heading" className="stack-tight">
        <h2 id="coverage-heading">Coverage</h2>
        <div className="stat-grid">
          <Stat label="Listed lines" value={formatInteger(data.securities_count)} />
          <Stat label="Issuers behind them" value={formatInteger(data.issuer_count)} />
          <Stat label="Price rows stored" value={formatInteger(data.price_rows)} />
          <Stat label="Latest price date" value={data.latest_price_date ?? UNAVAILABLE} caution={stale} />
          <Stat
            label="Feed age"
            value={
              data.price_feed_age_days === null
                ? UNAVAILABLE
                : `${data.price_feed_age_days} day${data.price_feed_age_days === 1 ? "" : "s"}`
            }
            caution={stale}
          />
          <Stat label="No price yet" value={formatInteger(data.securities_with_no_price)} />
        </div>
        {stale && (
          <div className="notice notice-caution" role="status">
            <h3>Price data is {data.price_feed_age_days} days old</h3>
            <p className="prose t-body">
              Models must refuse to emit new signals on stale inputs (§8), so this is surfaced rather
              than silently rendered as current. Check whether the market has simply been closed, or
              run the end-of-day snapshot.
            </p>
          </div>
        )}
      </section>

      <section aria-labelledby="survivorship-heading" className="stack-tight">
        <h2 id="survivorship-heading">Survivorship</h2>
        <div className="stat-grid">
          <Stat label="Issuers known to the exchange" value={formatInteger(data.registry_issuers)} />
          <Stat label="Flagged delisted" value={formatInteger(data.registry_delisted)} />
          <Stat
            label="Status unknown"
            value={formatInteger(data.registry_unknown_status)}
            caution={data.registry_unknown_status > 0}
          />
        </div>
        <div className="notice notice-caution">
          <h3>Survivorship is improved, not solved</h3>
          <p className="prose t-body">
            The traded universe contains only companies that still trade, which is the bias §7 and
            failure mode N&nbsp;#1 warn about — a backtest run on it would never see a company that
            failed. The exchange&rsquo;s own registry adds{" "}
            {formatInteger(data.registry_issuers - data.issuer_count)} more issuers and explicitly
            flags {formatInteger(data.registry_delisted)} as delisted, so those names are at least
            present.
          </p>
          <p className="prose t-body">
            Two limits worth stating plainly. {formatInteger(data.registry_delisted)} delistings
            across the exchange&rsquo;s entire history is implausibly few, so the flag is a partial
            record. And the {formatInteger(data.registry_unknown_status)} issuers that are neither
            trading nor flagged cannot be told apart here — debt-only issuers, suspensions and
            merely illiquid names look identical. No delisting <em>date</em> is published at all;
            the registry only bounds it between when we first and last saw the issuer.
          </p>
        </div>
      </section>

      <section aria-labelledby="queues-heading" className="stack-tight">
        <h2 id="queues-heading">Confirm queues</h2>
        <div className="stat-grid">
          <Stat label="Corporate actions pending" value={formatInteger(data.corporate_actions_pending)} />
          <Stat label="Corporate actions confirmed" value={formatInteger(data.corporate_actions_confirmed)} />
          <Stat label="Corporate actions rejected" value={formatInteger(data.corporate_actions_rejected)} />
          <Stat
            label="Fundamentals pending"
            value={formatInteger(data.fundamentals_pending_confirmation)}
          />
          <Stat label="Fundamentals confirmed" value={formatInteger(data.fundamentals_confirmed)} />
        </div>
        <div className="row">
          <button className="btn-primary" onClick={onOpenReview}>
            Open the confirm queue
          </button>
          {pending === 0 && (
            <span className="t-caption">Nothing is currently waiting for review.</span>
          )}
        </div>
      </section>

      <section aria-labelledby="integrity-heading" className="stack-tight">
        <h2 id="integrity-heading">Universe integrity</h2>
        <p className="prose">
          The weekly-tracked numbers from the data-integrity rollout — where a rising quarantine
          count early on is detection working, not a regression.
        </p>
        <div className="stat-grid">
          <Stat
            label="Issuers with a primary line"
            value={`${formatInteger(ui.issuers_with_a_primary_line)} / ${formatInteger(ui.issuers_total)}`}
            caution={ui.issuers_with_a_primary_line < ui.issuers_total}
          />
          <Stat
            label="High-confidence bindings"
            value={`${formatInteger(ui.issuers_high_confidence_binding)} / ${formatInteger(ui.issuers_total)}`}
          />
          <Stat
            label="Unknown instrument type"
            value={formatInteger(ui.lines_unknown_instrument_type)}
            caution={ui.lines_unknown_instrument_type > 0}
          />
          <Stat
            label="Quarantined lines"
            value={formatInteger(ui.quarantined_line_count)}
            caution={ui.quarantined_line_count > 0}
          />
          <Stat
            label="Market-cap identity pass"
            value={ui.market_cap_identity_pass_pct !== null ? `${ui.market_cap_identity_pass_pct}%` : UNAVAILABLE}
          />
          <Stat
            label="Price-ratio actions confirmed"
            value={
              ui.price_ratio_actions_confirmed_pct !== null
                ? `${ui.price_ratio_actions_confirmed_pct}%`
                : UNAVAILABLE
            }
          />
          <Stat
            label="Median price staleness"
            value={
              ui.median_price_staleness_days !== null
                ? `${ui.median_price_staleness_days} day${ui.median_price_staleness_days === 1 ? "" : "s"}`
                : UNAVAILABLE
            }
            caution={ui.median_price_staleness_days !== null && ui.median_price_staleness_days > 3}
          />
        </div>
        {Object.keys(ui.open_alerts_by_type).length > 0 && (
          <p className="t-caption muted" style={{ margin: 0 }}>
            Open alerts:{" "}
            {Object.entries(ui.open_alerts_by_type)
              .map(([t, c]) => `${t} ${c}`)
              .join(" · ")}
          </p>
        )}
      </section>

      <section aria-labelledby="export-heading" className="stack-tight">
        <h2 id="export-heading">Export</h2>
        <div className="row" style={{ alignItems: "flex-start", gap: "var(--s4)", flexWrap: "wrap" }}>
          <div className="stack-tight" style={{ maxWidth: 340 }}>
            <button onClick={handleDownloadWorkbook} disabled={workbookBusy}>
              {workbookBusy ? "Building…" : "Download Excel workbook"}
            </button>
            <p className="t-caption prose" style={{ margin: 0 }}>
              For analysis in Excel — companies, prices, financial statements, ratios, valuations,
              macro series and your portfolio, one sheet each. The valuations sheet re-runs a real
              full-universe pass, same as Opportunities, so this can take roughly a minute.
            </p>
            {workbookNotice && (
              <p className="t-caption" role="status" style={{ margin: 0, color: "var(--pos-strong)" }}>
                {workbookNotice}
              </p>
            )}
            {workbookError && (
              <p className="t-caption" role="alert" style={{ margin: 0, color: "var(--neg-strong)" }}>
                {workbookError}
              </p>
            )}
          </div>
          <div className="stack-tight" style={{ maxWidth: 340 }}>
            <button onClick={handleDownloadBackup} disabled={backupBusy}>
              {backupBusy ? "Building…" : "Download full backup"}
            </button>
            <p className="t-caption prose" style={{ margin: 0 }}>
              A complete, exact copy of every table (newline-delimited JSON per table, plus a
              checksummed manifest) — the actual disaster-recovery artefact, not the Excel workbook
              above. Keep this somewhere safe. Restore verification for this exact format was run
              against real data (<code>scripts/verify_backup_restore.py</code>) and confirmed every
              table's row count and checksum match — see <code>docs/audits/R1_FIX_LOG.md</code>.
            </p>
            {backupNotice && (
              <p className="t-caption" role="status" style={{ margin: 0, color: "var(--pos-strong)" }}>
                {backupNotice}
              </p>
            )}
            {backupError && (
              <p className="t-caption" role="alert" style={{ margin: 0, color: "var(--neg-strong)" }}>
                {backupError}
              </p>
            )}
          </div>
        </div>
      </section>

      <section aria-labelledby="quarantine-heading" className="stack-tight">
        <h2 id="quarantine-heading">Quarantined tickers</h2>
        {data.quarantined.length === 0 ? (
          <EmptyState title="No tickers are quarantined.">
            <p style={{ margin: 0 }}>
              Every ticker's stored adjustment factors reconcile against an independent recomputation
              from its confirmed corporate actions, within the 0.5% threshold (§7). A ticker appears
              here when that check fails, and is excluded from Opportunities ranking and Portfolio
              valuation until resolved — see docs/audits/R1_OPEN_ISSUES.md's OI-3 for the real gap
              this closed (that exclusion wasn't actually wired anywhere until this session, despite
              this list's own existence implying it was).
            </p>
          </EmptyState>
        ) : (
          <div className="table-wrap table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Ticker</th>
                  <th scope="col">Alert</th>
                  <th scope="col">Detail</th>
                  <th scope="col">Raised</th>
                </tr>
              </thead>
              <tbody>
                {data.quarantined.map((q) => (
                  <tr key={`${q.ticker}-${q.raised_at}`}>
                    <th scope="row" className="mono" style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}>
                      {q.ticker}
                    </th>
                    <td>{q.alert_type}</td>
                    <td className="prose">{q.detail}</td>
                    <td className="num">{new Date(q.raised_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <AsOf label={`Read from the local database at ${new Date().toLocaleTimeString()}`} />
    </div>
  );
}

function Stat({ label, value, caution }: { label: string; value: string; caution?: boolean }) {
  return (
    <div className="card">
      <div className="t-label">{label}</div>
      <div className="stat-value" style={caution ? { color: "var(--caution)" } : undefined}>
        {value}
      </div>
    </div>
  );
}
