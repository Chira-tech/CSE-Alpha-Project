import { useEffect, useState } from "react";
import { ApiRequestError, downloadBackup, downloadWorkbook, getDataHealth } from "../api";
import { AsOf, EmptyState, ErrorState, SkeletonCard } from "../components/states";
import { downloadBlob } from "../csv";
import { onDataRefreshed } from "../dataRefresh";
import { formatInteger, UNAVAILABLE } from "../format";
import type { CheckLedgerRow, CohortStat, DataHealth, LedgerTrendPoint } from "../types";

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
          Where data quality is actually maintained. Read it top to bottom: what is
          checkable, what is stopping work, then the checks, the worklist, and what has
          changed.
        </p>
      </header>

      {/* §11 — the one number to watch: not the pass rate (a statement about
          the data) but the checkable share (how much of the data we have any
          right to an opinion on). */}
      <section aria-labelledby="one-number-heading" className="stack-tight">
        <h2 id="one-number-heading" className="sr-only">
          Universe checkable
        </h2>
        <div className="card" style={{ display: "flex", alignItems: "baseline", gap: "var(--s4)", flexWrap: "wrap" }}>
          <div>
            <span className="t-label">Universe checkable</span>
            <div
              className="hero-value"
              style={{
                color:
                  data.universe_checkable_pct !== null && Number(data.universe_checkable_pct) < 50
                    ? "var(--caution)"
                    : undefined,
              }}
            >
              {data.universe_checkable_pct !== null ? `${data.universe_checkable_pct}%` : UNAVAILABLE}
            </div>
          </div>
          <p className="t-caption prose" style={{ maxWidth: 460, margin: 0 }}>
            The mean checkable share across the blocking checks. A high pass rate on a low
            checkable share knows less than a lower pass rate on a high one — this is the
            number to move.
          </p>
        </div>
      </section>

      {data.blockers.length > 0 && (
        <section aria-labelledby="blockers-heading" className="stack-tight">
          <h2 id="blockers-heading">Blocking work</h2>
          <ul className="decisions-list" style={{ borderLeft: 0, padding: 0 }}>
            {data.blockers.map((b, i) => (
              <li
                key={i}
                className="t-body"
                style={{
                  paddingLeft: "var(--s4)",
                  borderLeft: `2px solid ${b.severity === "red" ? "var(--neg)" : "var(--caution)"}`,
                  lineHeight: "22px",
                }}
              >
                <strong>{b.condition}</strong>
                <div className="t-caption muted">
                  causing&nbsp;— {b.causing}
                </div>
                <div className="t-caption" style={{ color: "var(--ink-2)" }}>
                  action&nbsp;— {b.action}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

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

        {/* Freshness, split: how old the newest data is (in TRADING days,
            so a weekend is not a gap) vs when the capture job last
            actually succeeded. Two quantities that were one label. */}
        <div className="stat-grid">
          <Stat label="Newest price date" value={data.latest_price_date ?? UNAVAILABLE} caution={stale} />
          <Stat
            label="Trading days behind"
            value={
              data.price_data_age_trading_days === null
                ? UNAVAILABLE
                : `${data.price_data_age_trading_days} session${
                    data.price_data_age_trading_days === 1 ? "" : "s"
                  }`
            }
            caution={
              data.price_data_age_trading_days !== null && data.price_data_age_trading_days > 1
            }
          />
          <Stat
            label="Price capture job last succeeded"
            value={
              data.price_capture_last_success_at === null
                ? "never"
                : `${data.price_capture_last_success_age_days}d ago`
            }
            caution={
              data.price_capture_last_success_at === null ||
              (data.price_capture_last_success_age_days ?? 0) > 2
            }
          />
          <Stat
            label="CBSL risk-free data through"
            value={data.macro_risk_free_data_date ?? UNAVAILABLE}
            caution={data.macro_risk_free_data_date === null}
          />
          <Stat
            label="Macro job last succeeded"
            value={
              data.macro_feed_last_success_at === null
                ? "never (data still current — see left)"
                : new Date(data.macro_feed_last_success_at).toLocaleDateString()
            }
          />
        </div>
        {/* §9.5 — one cell per exchange trading day (weekday), filled
            where price data exists, hollow where it does not. A weekend
            is simply absent; a missed weekday is a visible gap. */}
        <TradingCalendar
          latestPriceDate={data.latest_price_date}
          missing={data.missing_trading_days}
        />
        {data.missing_trading_days.length > 0 && (
          <p className="t-caption prose" style={{ margin: 0, color: "var(--caution)" }}>
            {data.missing_trading_days.length} weekday session
            {data.missing_trading_days.length === 1 ? "" : "s"} after the newest stored row have no
            price data ({data.missing_trading_days.join(", ")}) — a genuine gap, not a weekend. Run
            the end-of-day capture. (No exchange holiday calendar yet, so a weekday holiday shows
            here until one is added.)
          </p>
        )}
      </section>

      <section aria-labelledby="ledger-heading" className="stack-tight">
        <h2 id="ledger-heading">Check ledger</h2>
        <p className="prose">
          Every universe-wide check split three ways: <strong>pass</strong> (checked, agrees),{" "}
          <strong>fail</strong> (checked, disagrees), <strong>not evaluable</strong> (could not be
          checked). A pass rate over a check that can only see 3% of the universe is not the same as
          one that can see 95% — <em>checkable&nbsp;%</em> is the number to watch.
        </p>
        <div className="table-wrap table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Check</th>
                <th scope="col" className="right">Pass</th>
                <th scope="col" className="right">Fail</th>
                <th scope="col" className="right">Not eval.</th>
                <th scope="col" className="right">Checkable</th>
                <th scope="col" className="right">Pass of checkable</th>
                <th scope="col">14-day</th>
                <th scope="col">Blocking</th>
              </tr>
            </thead>
            <tbody>
              {[...data.check_ledger]
                .sort((a, b) => b.failed - a.failed || b.not_evaluable - a.not_evaluable)
                .map((r) => (
                  <CheckLedgerRowView
                    key={r.check}
                    row={r}
                    trend={data.check_ledger_trend[r.check] ?? []}
                  />
                ))}
            </tbody>
          </table>
        </div>
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
          <Stat
            label="Confirmed this week"
            value={`${formatInteger(data.fundamentals_confirmed_last_7d)} fig · ${formatInteger(
              data.corporate_actions_confirmed_last_7d,
            )} CA`}
          />
        </div>
        <p className="t-caption muted" style={{ margin: 0 }}>
          "Confirmed this week" is the burn-down rate — how fast the queue is being cleared, next to
          how much is left. Corroborated fundamentals (an independently-sourced filing already
          reporting the exact same figure) are auto-confirmed nightly and never reach the queue.
        </p>
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
            label="Market-cap identity — pass of checkable"
            value={ui.market_cap_identity_pass_pct !== null ? `${ui.market_cap_identity_pass_pct}%` : UNAVAILABLE}
          />
          <Stat
            label="Corp. actions — confirmed of reviewed"
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
          <Stat
            label="Suspended/delisted lines (trading status)"
            value={formatInteger(ui.suspended_or_delisted_lines)}
            caution={ui.suspended_or_delisted_lines > 0}
          />
          {(() => {
            const rf = data.macro_risk_free_data_date;
            const rfAgeDays = rf
              ? Math.round((Date.now() - new Date(rf).getTime()) / 86_400_000)
              : null;
            const rfStale = rfAgeDays === null || rfAgeDays > 30;
            return (
              <Stat
                label={rfStale ? "Cost of equity — risk-free rate stale" : "Cost of equity available"}
                value={
                  ui.cost_of_equity_available_pct !== null
                    ? `${ui.cost_of_equity_available_pct}%`
                    : UNAVAILABLE
                }
                caution={
                  rfStale ||
                  (ui.cost_of_equity_available_pct !== null &&
                    Number(ui.cost_of_equity_available_pct) < 95)
                }
              />
            );
          })()}
          <Stat
            label="Verdicts capped — negative earnings trend"
            value={formatInteger(ui.buy_side_verdicts_on_negative_earnings_trend)}
            caution={ui.buy_side_verdicts_on_negative_earnings_trend > 0}
          />
        </div>
        <p className="t-caption muted" style={{ margin: 0 }}>
          "Verdicts capped" is Check 8: names with a trailing net loss on a multi-year declining
          earnings trend. Their fair value is still shown, but any Buy-side verdict is withheld and
          the rating held at Hold — so the count of published buy-side calls on negative-trend names
          stays at zero.
        </p>
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

      {/* §9.3 — the worklist grouped by cause, never by ticker, so one
          action covers the cohort and you can't spend an afternoon on
          one name. */}
      <section aria-labelledby="worklist-heading" className="stack-tight">
        <h2 id="worklist-heading">Worklist by cause</h2>
        {data.worklist_groups.length === 0 ? (
          <EmptyState title="Nothing is quarantined.">
            <p style={{ margin: 0 }}>No open data-quality alert against any line.</p>
          </EmptyState>
        ) : (
          <div className="table-wrap table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Cause</th>
                  <th scope="col" className="right">Lines</th>
                  <th scope="col">Tickers</th>
                  <th scope="col">Action for the whole group</th>
                </tr>
              </thead>
              <tbody>
                {data.worklist_groups.map((g) => (
                  <tr key={g.alert_type}>
                    <th
                      scope="row"
                      style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}
                    >
                      {g.label}
                      <div className="t-caption muted" style={{ fontWeight: 400 }}>{g.alert_type}</div>
                    </th>
                    <td className="right num">{formatInteger(g.count)}</td>
                    <td className="t-caption mono">
                      {g.tickers.slice(0, 12).join(", ")}
                      {g.count > 12 ? ` … +${g.count - 12}` : ""}
                    </td>
                    <td className="t-caption">{g.suggested_action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* §9.4 — the experiment log on the page, so "one variable per
          deploy" is visible rather than aspirational. */}
      <section aria-labelledby="experiments-heading" className="stack-tight">
        <h2 id="experiments-heading">Experiment log</h2>
        <div className="table-wrap table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Hypothesis / variable</th>
                <th scope="col">Outcome</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.experiments.map((e) => (
                <tr key={e.id}>
                  <th
                    scope="row"
                    className="mono"
                    style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 600, color: "var(--ink-1)" }}
                  >
                    {e.id}
                  </th>
                  <td className="prose" style={{ maxWidth: 360 }}>
                    {e.hypothesis}
                    <div className="t-caption muted">variable: {e.variable}</div>
                  </td>
                  <td className="prose t-caption" style={{ maxWidth: 380 }}>{e.outcome}</td>
                  <td>
                    <span
                      className="status-tag"
                      style={{
                        color:
                          e.status === "confirmed" || e.status === "shipped"
                            ? "var(--pos-strong)"
                            : e.status === "falsified"
                              ? "var(--caution)"
                              : "var(--ink-3)",
                      }}
                    >
                      {e.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <AsOf label={`Read from the local database at ${new Date().toLocaleTimeString()}`} />
    </div>
  );
}

function TradingCalendar({
  latestPriceDate,
  missing,
}: {
  latestPriceDate: string | null;
  missing: string[];
}) {
  const missingSet = new Set(missing);
  const latest = latestPriceDate ? new Date(latestPriceDate + "T00:00:00") : null;
  const cells: { date: string; state: "filled" | "gap" | "future" }[] = [];
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  while (cells.length < 30) {
    const day = d.getDay();
    if (day !== 0 && day !== 6) {
      const iso = d.toISOString().slice(0, 10);
      const state = missingSet.has(iso)
        ? "gap"
        : latest && d.getTime() <= latest.getTime()
          ? "filled"
          : "future";
      cells.unshift({ date: iso, state });
    }
    d.setDate(d.getDate() - 1);
  }
  const color = (s: string) =>
    s === "filled" ? "var(--brand-300)" : s === "gap" ? "var(--caution)" : "var(--surface-sunken)";
  return (
    <div style={{ display: "flex", gap: 3, flexWrap: "wrap", alignItems: "center" }} aria-label="Trading-day price coverage, last 30 sessions">
      {cells.map((c) => (
        <span
          key={c.date}
          title={`${c.date}: ${c.state === "filled" ? "price data" : c.state === "gap" ? "MISSING" : "no session yet"}`}
          style={{
            width: 12,
            height: 12,
            borderRadius: 2,
            background: c.state === "filled" ? color("filled") : "transparent",
            border: c.state === "filled" ? "none" : `1px solid ${color(c.state)}`,
          }}
        />
      ))}
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

function Sparkline({ points }: { points: LedgerTrendPoint[] }) {
  const vals = points
    .map((p) => (p.checkable_pct === null ? null : Number(p.checkable_pct)))
    .filter((v): v is number => v !== null);
  if (vals.length < 2) {
    return <span className="t-caption muted">{vals.length === 1 ? "1 pt" : "—"}</span>;
  }
  const w = 72;
  const h = 18;
  const max = 100;
  const step = w / (vals.length - 1);
  const d = vals
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`)
    .join(" ");
  const last = vals[vals.length - 1];
  const first = vals[0];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ overflow: "visible" }} aria-hidden>
      <path d={d} fill="none" stroke="var(--ink-3)" strokeWidth="1" />
      <circle
        cx={w}
        cy={h - (last / max) * h}
        r="1.6"
        fill={last >= first ? "var(--pos-strong)" : "var(--neg-strong)"}
      />
    </svg>
  );
}

function CheckLedgerRowView({ row, trend }: { row: CheckLedgerRow; trend: LedgerTrendPoint[] }) {
  const checkable = row.checkable_pct === null ? null : Number(row.checkable_pct);
  const reasons = Object.entries(row.not_evaluable_reasons);
  // Amber, never red: a check that can barely see the universe, or is
  // waiting on a feed that never ran, is unfinished work — not a failure.
  const rowCaution = row.failed > 0 || (checkable !== null && checkable < 50);
  return (
    <tr>
      <th
        scope="row"
        style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}
      >
        {row.label}
        {reasons.length > 0 && (
          <div className="t-caption muted" style={{ fontWeight: 400, marginTop: 2 }}>
            not evaluable: {reasons.map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}
          </div>
        )}
      </th>
      <td className="right num" style={{ color: "var(--pos-strong)" }}>{formatInteger(row.passed)}</td>
      <td className="right num" style={row.failed > 0 ? { color: "var(--neg-strong)" } : undefined}>
        {formatInteger(row.failed)}
      </td>
      <td className="right num muted">{formatInteger(row.not_evaluable)}</td>
      <td
        className="right num"
        style={checkable !== null && checkable < 50 ? { color: "var(--caution)" } : undefined}
      >
        {checkable === null ? UNAVAILABLE : `${row.checkable_pct}%`}
      </td>
      <td className="right num">
        {row.pass_pct_of_checkable === null ? UNAVAILABLE : `${row.pass_pct_of_checkable}%`}
      </td>
      <td>
        <Sparkline points={trend} />
      </td>
      <td>
        <span className={`status-tag ${row.blocking ? "status-pending" : ""}`}>
          {row.blocking ? "blocking" : "report-only"}
        </span>
        {rowCaution && <span aria-hidden> ⚠</span>}
        {row.cohorts && <CohortSplit cohorts={row.cohorts} />}
      </td>
    </tr>
  );
}

function CohortSplit({ cohorts }: { cohorts: Record<string, CohortStat> }) {
  const rows = Object.entries(cohorts).filter(([, c]) => c.passed + c.failed + c.not_evaluable > 0);
  if (rows.length < 2) return null;
  // Flag a cohort whose fail rate (of what it could check) is at least
  // double the row's overall — the "concentrates in one cohort" signal.
  const rates = rows.map(([, c]) => (c.passed + c.failed ? c.failed / (c.passed + c.failed) : null));
  const worst = Math.max(...rates.filter((r): r is number => r !== null), 0);
  return (
    <div className="t-caption muted" style={{ fontWeight: 400, marginTop: 2 }}>
      {rows.map(([k, c], i) => {
        const rate = rates[i];
        const hot = rate !== null && worst > 0 && rate === worst && rate >= 0.1 && rows.length > 1;
        return (
          <div key={k} style={hot ? { color: "var(--caution)" } : undefined}>
            {k}: {c.failed}✗ / {c.passed + c.failed} checked
            {c.not_evaluable > 0 ? ` · ${c.not_evaluable} n/e` : ""}
          </div>
        );
      })}
    </div>
  );
}
