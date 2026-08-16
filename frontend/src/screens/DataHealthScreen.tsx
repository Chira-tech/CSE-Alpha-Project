import { useEffect, useState } from "react";
import { ApiRequestError, getDataHealth } from "../api";
import { AsOf, EmptyState, ErrorState, SkeletonCard } from "../components/states";
import { formatInteger, UNAVAILABLE } from "../format";
import type { DataHealth } from "../types";

export function DataHealthScreen({ onOpenReview }: { onOpenReview: () => void }) {
  const [data, setData] = useState<DataHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDataHealth()
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
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
          <Stat label="Securities" value={formatInteger(data.securities_count)} />
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

      <section aria-labelledby="quarantine-heading" className="stack-tight">
        <h2 id="quarantine-heading">Quarantined tickers</h2>
        {data.quarantined.length === 0 ? (
          <EmptyState title="No tickers are quarantined.">
            <p style={{ margin: 0 }}>
              Every ticker's stored adjustment factors reconcile against an independent recomputation
              from its confirmed corporate actions, within the 0.5% threshold (§7). A ticker appears
              here when that check fails, and is excluded from every model until resolved.
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
