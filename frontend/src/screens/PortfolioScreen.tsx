import { useEffect, useRef, useState } from "react";
import { ApiRequestError, getPortfolioHoldingsValued, uploadPortfolio } from "../api";
import { Delta } from "../components/Delta";
import { TrendChip } from "../components/TrendChip";
import { EmptyState, ErrorState, SkeletonTable } from "../components/states";
import { ZoneChip } from "../components/ZoneChip";
import { directionOf, formatPrice, UNAVAILABLE } from "../format";
import type { ValuedPortfolio, ValuedPosition } from "../types";

/**
 * §7.1 Portfolio: "what I own, and whether the reasons still hold."
 *
 * The full Phase 8 engine (§41–42) — thesis status, distance to each
 * exit trigger, portfolio-level factor exposure, the thesis-drift
 * verdict — needs the decision record (§45) capturing frozen model
 * state at purchase, which doesn't exist yet. What's real and built
 * here is the narrower, immediately useful slice this session shipped
 * on the backend: your actual current holdings, read from a real CDS/
 * broker export you upload, run through this system's own real
 * valuation engine. P&L is shown, but deliberately below the fair-value
 * columns — §41's own ordering, because P&L is what happened and fair
 * value is what to do about it now.
 *
 * Every upload creates a new, permanent snapshot (Design Law 2 — never
 * overwrites a prior one), so re-uploading after a trade is exactly how
 * this screen is meant to stay current.
 */
export function PortfolioScreen({ onOpen }: { onOpen: (ticker: string) => void }) {
  const [data, setData] = useState<ValuedPortfolio | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  function load() {
    setError(null);
    getPortfolioHoldingsValued()
      .then(setData)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }

  useEffect(load, []);

  async function handleFileChosen(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      await uploadPortfolio(file);
      load();
    } catch (e) {
      setUploadError(e instanceof ApiRequestError ? e.message : String(e));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  const uploadControl = (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: "var(--s2)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--s3)", flexWrap: "wrap" }}>
        <button
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          className="btn-primary"
        >
          {uploading ? "Uploading…" : data ? "Upload updated holdings" : "Upload your portfolio"}
        </button>
        <span className="t-caption">
          A real CDS/broker holdings export (.xlsx). Each upload is kept as a new, permanent record —
          nothing is ever overwritten, so this is exactly what to do after a buy or sell.
        </span>
        <input
          ref={fileInput}
          type="file"
          accept=".xlsx"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFileChosen(file);
          }}
        />
      </div>
      {uploadError && (
        <p className="prose t-body" style={{ color: "var(--neg)" }}>
          Upload failed: {uploadError}
        </p>
      )}
    </div>
  );

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Portfolio</h1>
        <p className="prose">What I own, and whether the reasons still hold.</p>
      </header>

      {uploadControl}

      {error ? (
        <ErrorState
          whatFailed="Your portfolio could not be loaded"
          whatItAffects="This screen only."
          whatStillWorks="Every other screen, which reads independent data."
          whatHappensNext={`Check the API is running, then reload. Underlying error: ${error}`}
        />
      ) : data === undefined ? (
        <SkeletonTable rows={6} columns={7} />
      ) : data === null ? (
        <EmptyState title="No portfolio uploaded yet">
          <p style={{ margin: 0 }}>
            Upload a real holdings export from your CDS/broker account above to see your current
            positions valued against this system's own fair-value engine — no sample data is shown
            in its place.
          </p>
        </EmptyState>
      ) : (
        <PortfolioBody data={data} onOpen={onOpen} />
      )}
    </div>
  );
}

function PortfolioBody({ data, onOpen }: { data: ValuedPortfolio; onOpen: (ticker: string) => void }) {
  const totalGain =
    data.total_live_market_value !== null
      ? Number(data.total_live_market_value) - Number(data.total_cost)
      : null;
  const totalGainPct = totalGain !== null ? (totalGain / Number(data.total_cost)) * 100 : null;

  return (
    <div className="stack-tight">
      <section aria-labelledby="portfolio-summary-heading" className="stack-tight">
        <h2 id="portfolio-summary-heading">Summary</h2>
        <div className="card" style={{ display: "flex", gap: "var(--s6)", flexWrap: "wrap" }}>
          <div>
            <span className="t-label">Cost</span>
            <div className="hero-value" style={{ fontSize: 24 }}>{formatPrice(data.total_cost)}</div>
          </div>
          <div>
            <span className="t-label">Live market value</span>
            <div className="hero-value" style={{ fontSize: 24 }}>
              {data.total_live_market_value !== null ? formatPrice(data.total_live_market_value) : UNAVAILABLE}
            </div>
          </div>
          <div>
            <span className="t-label">Unrealised P&amp;L</span>
            <div className="hero-value" style={{ fontSize: 24 }}>
              {totalGain !== null ? (
                <span className={`delta delta-${directionOf(totalGain)}`}>
                  {totalGain >= 0 ? "+" : ""}
                  {formatPrice(String(totalGain))}
                </span>
              ) : (
                UNAVAILABLE
              )}
            </div>
            {totalGainPct !== null && (
              <div className="t-caption">
                <Delta percentage={totalGainPct} />
              </div>
            )}
          </div>
        </div>

        {/* R1 T4.5.1 — three windows here (Today's own portfolio block gets
            four); see `value_trend_pct`'s own docstring for the real,
            disclosed assumption (today's holdings, past real prices). */}
        <TrendChip
          windows={["15d", "30d", "45d"].map((label) => ({
            label,
            pct:
              data.value_trend_pct[label] !== null && data.value_trend_pct[label] !== undefined
                ? Number(data.value_trend_pct[label])
                : null,
          }))}
        />

        {data.positions_missing_a_live_price.length > 0 && (
          <div className="notice notice-caution" role="status">
            <h3>
              {data.positions_missing_a_live_price.length} position
              {data.positions_missing_a_live_price.length === 1 ? "" : "s"} missing a live price
            </h3>
            <p className="prose t-body">
              {data.positions_missing_a_live_price.join(", ")} — no real price history for
              {data.positions_missing_a_live_price.length === 1 ? " this ticker" : " these tickers"} as
              of {data.as_of}, so the totals above exclude
              {data.positions_missing_a_live_price.length === 1 ? " its" : " their"} contribution
              rather than guessing.
            </p>
          </div>
        )}
      </section>

      <section aria-labelledby="positions-heading" className="stack-tight">
        <h2 id="positions-heading">Positions</h2>
        <div className="table-wrap table-scroll">
          <table className="data-table">
            <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
              As of {data.as_of}. Fair value, zone and buy-below come from this system's own real
              valuation engine (§16–26) — a blank cell means the engine doesn't yet have what it
              needs for that name, never a guess.
            </caption>
            <thead>
              <tr>
                <th scope="col">Ticker</th>
                <th scope="col" className="right">Quantity</th>
                <th scope="col" className="right">Avg price</th>
                <th scope="col" className="right">Live price</th>
                <th scope="col" className="right">Live value</th>
                <th scope="col" className="right">Unrealised P&amp;L</th>
                <th scope="col" className="right">Fair value</th>
                <th scope="col">Zone</th>
                <th scope="col" className="right">Sell above</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p) => (
                <PositionRow key={p.ticker} p={p} onOpen={onOpen} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function PositionRow({ p, onOpen }: { p: ValuedPosition; onOpen: (ticker: string) => void }) {
  const gain = p.live_unrealized_gain_loss !== null ? Number(p.live_unrealized_gain_loss) : null;
  const gainPct = gain !== null && Number(p.total_cost) !== 0 ? (gain / Number(p.total_cost)) * 100 : null;

  return (
    <tr>
      <th scope="row" style={rowHeadStyle}>
        <button className="btn-link mono" onClick={() => onOpen(p.ticker)}>
          {p.ticker}
        </button>
        {p.warnings.length > 0 && (
          <span
            className="chip"
            title={p.warnings.join(" ")}
            style={{ marginLeft: "var(--s2)", borderColor: "var(--border-strong)", color: "var(--ink-3)" }}
          >
            i
          </span>
        )}
        {/* R1 T4.5.4: real attention flags, calm styling (§1 law 6 — no
            alarm colour), one chip per flag so each has its own tooltip
            rather than a single opaque "issues" indicator. */}
        {p.attention_flags.map((f) => (
          <span
            key={f.key}
            className="chip"
            title={f.detail}
            style={{ marginLeft: "var(--s1)", borderColor: "var(--border-strong)", color: "var(--ink-3)" }}
          >
            {f.label}
          </span>
        ))}
      </th>
      <td className="right num">{p.quantity}</td>
      <td className="right num">{formatPrice(p.avg_price)}</td>
      <td className="right num">{p.live_current_price !== null ? formatPrice(p.live_current_price) : UNAVAILABLE}</td>
      <td className="right num">{p.live_market_value !== null ? formatPrice(p.live_market_value) : UNAVAILABLE}</td>
      <td className="right">
        {gainPct !== null ? (
          <Delta percentage={gainPct} />
        ) : (
          <span className="muted">{UNAVAILABLE}</span>
        )}
      </td>
      <td className="right num">
        {/* `price_ladder_zone === null` covers THREE distinct cases: "no
            fair value at all", "a real but non-positive fair value"
            (`compute_price_ladder` refuses to build zones from the
            latter), and, since TASK 0.1, "a real positive fair value
            that failed the plausibility gate" (`app.domain.sanity`) —
            in every case the raw per-share figure isn't meaningful to
            show as a price, so both columns fall back to the same
            honest "unavailable" the zone itself already shows, rather
            than a confusing negative or implausible number. */}
        {p.price_ladder_zone !== null && p.blended_fair_value_per_share !== null
          ? formatPrice(p.blended_fair_value_per_share)
          : UNAVAILABLE}
      </td>
      <td>
        <ZoneChip zone={p.price_ladder_zone} why={p.warnings.join(" ") || undefined} />
      </td>
      <td className="right num">
        {/* R1 T4.5.3: for a HELD position, the take-profit ceiling is the
            actionable threshold — buy-below is the wrong signal once you
            already own the name. Thesis-break (warnings) is a SEPARATE,
            earlier exit trigger — this price alone is never the only one. */}
        {p.price_ladder_zone !== null && p.sell_above_price !== null ? formatPrice(p.sell_above_price) : UNAVAILABLE}
      </td>
    </tr>
  );
}


const rowHeadStyle = {
  background: "none",
  textTransform: "none" as const,
  letterSpacing: 0,
  fontSize: 13,
  fontWeight: 500,
  color: "var(--ink-1)",
};
