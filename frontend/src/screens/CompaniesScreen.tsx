import { useEffect, useMemo, useState } from "react";
import { ApiRequestError, listSecurities } from "../api";
import { formatMagnitude, formatPrice, UNAVAILABLE } from "../format";
import type { SecurityListItem } from "../types";

export function CompaniesScreen({ onOpen }: { onOpen: (ticker: string) => void }) {
  const [all, setAll] = useState<SecurityListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    listSecurities()
      .then(setAll)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : "Failed to load"));
  }, []);

  // Filter client-side: the whole universe is ~283 rows, so a round trip
  // per keystroke would add latency for nothing. The server-side `search`
  // parameter exists for callers that don't hold the full list.
  const rows = useMemo(() => {
    if (!all) return null;
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter((r) => r.ticker.toLowerCase().includes(q) || r.name.toLowerCase().includes(q));
  }, [all, query]);

  if (error) return <p className="error-text">Couldn't load companies: {error}</p>;
  if (!rows) return <p className="muted">Loading…</p>;

  return (
    <div className="stack">
      <div className="toolbar">
        <input
          type="search"
          className="search-input"
          placeholder="Filter by ticker or name…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="muted">
          {rows.length} of {all?.length ?? 0} companies
        </span>
      </div>

      <table className="queue-table">
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Company</th>
            <th className="right">Last close (LKR)</th>
            <th className="right">Turnover (LKR)</th>
            <th className="right">Volume</th>
            <th>As at</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.ticker} className="row-clickable" onClick={() => onOpen(r.ticker)}>
              <td className="mono">
                {r.ticker}
                {r.quarantined && (
                  <span className="quarantine-badge" title="Quarantined by a data-quality alert">
                    quarantined
                  </span>
                )}
              </td>
              <td>{r.name}</td>
              <td className="right num">{formatPrice(r.last_close)}</td>
              <td className="right num">{formatMagnitude(r.turnover)}</td>
              <td className="right num">
                {r.volume === null ? UNAVAILABLE : r.volume.toLocaleString("en-LK")}
              </td>
              <td className="num">{r.last_price_date ?? UNAVAILABLE}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="provenance-note">
        Every listed company is here, per Master Spec §10 — coverage is deliberately the full
        universe, not a pre-filtered shortlist. Scores, fair values and coverage tiers are not shown
        because the engines that compute them (Phases 2–3) don't exist yet; showing a placeholder
        number in a financial product is the one thing the UI specification forbids outright.
      </p>
    </div>
  );
}
