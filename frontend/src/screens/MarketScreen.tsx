import { useEffect, useState } from "react";
import { ApiRequestError, getMarketOverview } from "../api";
import { Delta } from "../components/Delta";
import { formatIndexValue, formatMagnitude } from "../format";
import type { MarketOverview } from "../types";

export function MarketScreen() {
  const [data, setData] = useState<MarketOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMarketOverview()
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : "Failed to load"));
  }, []);

  if (error) return <p className="error-text">Couldn't reach the CSE feed: {error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  // The ASPI is returned both as its own object and inside the sector
  // list (the CSE feed includes "ALL SHARE PRICE INDEX" as a row). Drop
  // the duplicate rather than showing the same number twice.
  const sectors = data.sectors.filter((s) => s.symbol !== "ASI");

  return (
    <div className="stack">
      <section className="hero-card">
        <div className="hero-label">All Share Price Index</div>
        <div className="hero-value num">{formatIndexValue(data.aspi?.value)}</div>
        <div className="hero-meta">
          <Delta percentage={data.aspi?.percentage} />
          <span className="muted">
            day range {formatIndexValue(data.aspi?.low)} – {formatIndexValue(data.aspi?.high)}
          </span>
          <span className="status-pill">{data.status}</span>
        </div>
      </section>

      <section>
        <h2>Sector indices</h2>
        <table className="queue-table">
          <thead>
            <tr>
              <th>Sector</th>
              <th className="right">Index</th>
              <th className="right">Change</th>
              <th className="right">Turnover today (LKR)</th>
            </tr>
          </thead>
          <tbody>
            {sectors.map((s) => (
              <tr key={s.name}>
                <td>{s.name}</td>
                <td className="right num">{formatIndexValue(s.index_value)}</td>
                <td className="right">
                  <Delta percentage={s.percentage} />
                </td>
                <td className="right num">{formatMagnitude(s.turnover_today)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <p className="provenance-note">
        Live passthrough from cse.lk, fetched {new Date(data.fetched_at).toLocaleString()}. Not stored
        and not point-in-time — these figures are for orientation only and no model reads them. The
        macro engine (Master Spec §29–33, Phase 5) is what turns these into a regime read and the
        earnings-yield-minus-T-bill spread that belongs on this screen.
      </p>
    </div>
  );
}
