import { useEffect, useMemo, useState } from "react";
import { ApiRequestError, listSecurities } from "../api";
import { EmptyState, ErrorState, SkeletonTable } from "../components/states";
import { formatMagnitude, formatPrice, UNAVAILABLE } from "../format";
import type { SecurityListItem } from "../types";

const PAGE_SIZE = 60;

export function CompaniesScreen({ onOpen }: { onOpen: (ticker: string) => void }) {
  const [all, setAll] = useState<SecurityListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE_SIZE);

  useEffect(() => {
    listSecurities()
      .then(setAll)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }, []);

  const filtered = useMemo(() => {
    if (!all) return null;
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (r) =>
        r.ticker.toLowerCase().includes(q) ||
        r.name.toLowerCase().includes(q) ||
        (r.cse_sector ?? "").toLowerCase().includes(q)
    );
  }, [all, query]);

  useEffect(() => setShown(PAGE_SIZE), [query]);

  // The CSE lists LINES, not companies: 18 issuers have both a voting and
  // a non-voting line, so "283 companies" overstates the universe by 19.
  const issuerCount = useMemo(
    () => (all ? new Set(all.map((r) => r.issuer_code ?? r.ticker)).size : null),
    [all]
  );

  if (error) {
    return (
      <div className="route stack">
        <header className="screen-head">
          <h1>Companies</h1>
        </header>
        <ErrorState
          whatFailed="The company list could not be loaded"
          whatItAffects="This screen, and the company files reached from it."
          whatStillWorks="Today and Macro, which read the live CSE feed rather than the local database."
          whatHappensNext={
            <>
              The API may not be running, or the database may not be bootstrapped. Start the backend,
              then run <span className="code-hint">python -m app.cli bootstrap</span> to populate the
              universe. Underlying error: {error}
            </>
          }
        />
      </div>
    );
  }

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Companies</h1>
        <p className="prose">
          Every listed company gets a file, whether or not it is investable — §10 separates analysis
          coverage from capital eligibility deliberately, so nothing is hidden, only labelled.
        </p>
        <p className="prose t-body">
          The exchange lists <em>lines</em>, not companies. Several issuers — mostly banks — have a
          voting and a non-voting line trading separately, and a few listed lines are fund units or
          rights rather than equity at all. Both are tagged below, and the count is given in lines
          and issuers so neither number has to be guessed at.
        </p>
      </header>

      <div className="toolbar">
        <div className="search-wrap">
          <label htmlFor="company-search" className="t-label">
            Filter
          </label>
          <input
            id="company-search"
            type="search"
            placeholder="Ticker, company name or sector…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {filtered && (
          <span className="t-caption" role="status">
            {filtered.length} of {all?.length ?? 0} lines
            {issuerCount !== null && ` · ${issuerCount} issuers`}
          </span>
        )}
      </div>

      {!filtered ? (
        <SkeletonTable rows={10} columns={7} />
      ) : filtered.length === 0 ? (
        <EmptyState title={`No company matches "${query}".`}>
          <p style={{ margin: 0 }}>
            Try a shorter fragment of the ticker or name. If the whole list is empty, the database
            has not been bootstrapped yet — run{" "}
            <span className="code-hint">python -m app.cli bootstrap</span>.
          </p>
        </EmptyState>
      ) : (
        <>
          <div className="table-wrap table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Ticker</th>
                  <th scope="col">Company</th>
                  <th scope="col">Sector</th>
                  <th scope="col" className="right">Last close (LKR)</th>
                  <th scope="col" className="right">Turnover (LKR)</th>
                  <th scope="col" className="right">Volume</th>
                  <th scope="col">As at</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, shown).map((r) => (
                  <tr
                    key={r.ticker}
                    className="selectable"
                    onClick={() => onOpen(r.ticker)}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onOpen(r.ticker);
                      }
                    }}
                  >
                    <th scope="row" className="mono" style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, color: "var(--ink-1)", fontWeight: 500 }}>
                      {r.ticker}
                      {r.quarantined && (
                        <>
                          {" "}
                          <span className="status-tag status-pending">quarantined</span>
                        </>
                      )}
                    </th>
                    <td>
                      {r.name}
                      {r.instrument_type && r.instrument_type !== "ordinary" && (
                        <>
                          {" "}
                          <span className="status-tag">
                            {r.instrument_type.replace("_", "-")}
                          </span>
                        </>
                      )}
                    </td>
                    <td>
                      {r.cse_sector ?? <span className="unavailable">{UNAVAILABLE}</span>}
                    </td>
                    <td className="right num">{formatPrice(r.last_close)}</td>
                    <td className="right num">{formatMagnitude(r.turnover)}</td>
                    <td className="right num">
                      {r.volume === null ? (
                        <span className="unavailable">{UNAVAILABLE}</span>
                      ) : (
                        r.volume.toLocaleString("en-LK")
                      )}
                    </td>
                    <td className="num">
                      {r.last_price_date ?? <span className="unavailable">{UNAVAILABLE}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* §17 forbids infinite scroll on a ranked list: "Ranking implies
              a cut-off. Show the top N and say what N is." */}
          {shown < filtered.length && (
            <div className="row">
              <button onClick={() => setShown((s) => s + PAGE_SIZE)}>
                Show {Math.min(PAGE_SIZE, filtered.length - shown)} more
              </button>
              <span className="t-caption">
                Showing {shown} of {filtered.length}
              </span>
            </div>
          )}
        </>
      )}

      <p className="t-caption prose">
        Scores, fair values and coverage tiers are absent because the engines that compute them
        (Phases 2–3) do not exist yet — not because they are zero.
      </p>
    </div>
  );
}
