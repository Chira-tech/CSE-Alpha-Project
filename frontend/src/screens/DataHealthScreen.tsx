import { useEffect, useState } from "react";
import { ApiRequestError, getDataHealth } from "../api";
import { formatInteger, UNAVAILABLE } from "../format";
import type { DataHealth } from "../types";

export function DataHealthScreen() {
  const [data, setData] = useState<DataHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDataHealth()
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : "Failed to load"));
  }, []);

  if (error) return <p className="error-text">Couldn't load data health: {error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  // §8: stale data is labelled plainly with its age, never silently
  // rendered as current. The threshold mirrors §50's ">36h" monitor,
  // expressed in days here since the store is daily EOD.
  const stale = data.price_feed_age_days !== null && data.price_feed_age_days > 2;

  return (
    <div className="stack">
      <section>
        <h2>Coverage</h2>
        <div className="stat-row">
          <Stat label="Securities" value={formatInteger(data.securities_count)} />
          <Stat label="Price rows stored" value={formatInteger(data.price_rows)} />
          <Stat
            label="Latest price date"
            value={data.latest_price_date ?? UNAVAILABLE}
            caution={stale}
          />
          <Stat
            label="Feed age"
            value={
              data.price_feed_age_days === null
                ? UNAVAILABLE
                : `${data.price_feed_age_days} day${data.price_feed_age_days === 1 ? "" : "s"}`
            }
            caution={stale}
          />
          <Stat label="Securities with no price" value={formatInteger(data.securities_with_no_price)} />
        </div>
        {stale && (
          <p className="stale-banner">
            Price data is {data.price_feed_age_days} days old. Run the EOD snapshot, or check whether
            the market has been closed. Models must refuse to emit new signals on stale inputs (§8).
          </p>
        )}
      </section>

      <section>
        <h2>Confirm queues</h2>
        <div className="stat-row">
          <Stat label="Corporate actions — pending" value={formatInteger(data.corporate_actions_pending)} />
          <Stat label="Corporate actions — confirmed" value={formatInteger(data.corporate_actions_confirmed)} />
          <Stat label="Corporate actions — rejected" value={formatInteger(data.corporate_actions_rejected)} />
          <Stat
            label="Fundamentals — pending"
            value={formatInteger(data.fundamentals_pending_confirmation)}
          />
          <Stat label="Fundamentals — confirmed" value={formatInteger(data.fundamentals_confirmed)} />
        </div>
      </section>

      <section>
        <h2>Quarantined tickers</h2>
        {data.quarantined.length === 0 ? (
          <p className="muted">
            None. Every ticker's stored adjustment factors reconcile against an independent
            recomputation from its confirmed corporate actions (§7).
          </p>
        ) : (
          <table className="queue-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Alert</th>
                <th>Detail</th>
                <th>Raised</th>
              </tr>
            </thead>
            <tbody>
              {data.quarantined.map((q) => (
                <tr key={`${q.ticker}-${q.raised_at}`}>
                  <td className="mono">{q.ticker}</td>
                  <td>{q.alert_type}</td>
                  <td>{q.detail}</td>
                  <td className="num">{new Date(q.raised_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, caution }: { label: string; value: string; caution?: boolean }) {
  return (
    <div className="stat">
      <div className="field-label">{label}</div>
      <div className={caution ? "stat-value num caution-text" : "stat-value num"}>{value}</div>
    </div>
  );
}
