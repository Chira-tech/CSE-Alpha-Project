import { useEffect, useRef, useState } from "react";
import { ApiRequestError, getPortfolioHoldingsValued, uploadPortfolio } from "../api";
import { AllocationDonut, type AllocationSlice } from "../components/AllocationDonut";
import { Delta } from "../components/Delta";
import { NeedsAttentionStrip } from "../components/NeedsAttentionStrip";
import { PortfolioValueChart } from "../components/PortfolioValueChart";
import { Sparkline } from "../components/Sparkline";
import { EmptyState, ErrorState, SkeletonTable } from "../components/states";
import { ZoneChip } from "../components/ZoneChip";
import { ZoneDistributionBar } from "../components/ZoneDistributionBar";
import { directionOf, formatMagnitude, formatPrice, UNAVAILABLE } from "../format";
import type { ValuedPortfolio, ValuedPosition } from "../types";

/**
 * §7.1 Portfolio: "what I own, and whether the reasons still hold."
 *
 * Rebuilt against `docs/CSE_Alpha_Engine_Portfolio_Redesign.md`: the
 * page now leads with what needs a decision (the attention strip), then
 * shows the portfolio's value over time as a chart rather than three
 * lonely numbers, its allocation and concentration as a chart rather
 * than nothing, and §15's portfolio-level reads (beta, trailing
 * dividend income, zone distribution) as stat tiles. The positions
 * table's per-row reasoning moved out of the ticker cell — which was
 * making row heights random — into a one-click expandable row, so the
 * grid is scannable and the reasoning is still exactly one click deep.
 *
 * Two pieces stay genuinely unbuilt and the screen is honest about it:
 * Realized P&L needs a buy/sell transaction log this system does not
 * have (§41) — its tile is a disclosed placeholder, never a fabricated
 * number — and §42's thesis-drift monitor needs a frozen purchase-time
 * baseline (§45's decision record) that doesn't exist, so "thesis
 * weakening" is real attention flags, not a drift-from-purchase read.
 *
 * Every upload creates a new, permanent snapshot (Design Law 2 — never
 * overwrites a prior one), so re-uploading after a trade is exactly how
 * this screen stays current.
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

  return (
    <div className="route stack">
      <header className="screen-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--s3)" }}>
        <div>
          <h1>Portfolio</h1>
          <p className="prose">What I own, and whether the reasons still hold.</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--s2)", flexShrink: 0 }}>
          <button onClick={() => fileInput.current?.click()} disabled={uploading} className="btn-primary">
            {uploading ? "Uploading…" : data ? "Upload updated holdings" : "Upload holdings"}
          </button>
          <span
            className="chip"
            role="img"
            aria-label="About uploading holdings"
            title="A real CDS/broker holdings export (.xlsx). Each upload is kept as a new, permanent record — nothing is ever overwritten, so this is exactly what to do after a buy or sell."
            style={{ cursor: "help", borderColor: "var(--border-strong)", color: "var(--ink-3)" }}
          >
            i
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
      </header>

      {uploadError && (
        <div className="notice notice-caution" role="status">
          <p className="prose t-body" style={{ margin: 0 }}>Upload failed: {uploadError}</p>
        </div>
      )}

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
  const totalCost = Number(data.total_cost);
  const totalLive = data.total_live_market_value !== null ? Number(data.total_live_market_value) : null;
  const totalGain = totalLive !== null ? totalLive - totalCost : null;
  const totalGainPct = totalGain !== null && totalCost !== 0 ? (totalGain / totalCost) * 100 : null;

  const byHolding: AllocationSlice[] = data.positions
    .filter((p) => p.live_market_value !== null)
    .map((p) => ({ key: p.ticker, label: p.ticker, value: Number(p.live_market_value) }));
  const bySector: AllocationSlice[] = data.rollups.sector_allocation.map((s) => ({
    key: s.sector,
    label: s.sector,
    value: Number(s.market_value),
  }));

  const priced = data.positions.filter((p) => p.live_market_value !== null);
  const top3 = [...priced]
    .sort((a, b) => Number(b.live_market_value) - Number(a.live_market_value))
    .slice(0, 3)
    .reduce((sum, p) => sum + Number(p.live_market_value), 0);
  const top3Pct = totalLive && totalLive > 0 ? (top3 / totalLive) * 100 : null;

  const beta = data.rollups.portfolio_beta !== null ? Number(data.rollups.portfolio_beta) : null;
  const betaCoverage = Number(data.rollups.beta_coverage_pct);
  const dividend =
    data.rollups.trailing_dividend_income !== null ? Number(data.rollups.trailing_dividend_income) : null;

  return (
    <div className="stack-tight">
      <NeedsAttentionStrip positions={data.positions} onOpen={onOpen} />

      <div
        style={{
          display: "grid",
          gap: "var(--s4)",
          gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
          alignItems: "start",
        }}
      >
        <div className="card">
          <PortfolioValueChart series={data.value_series} totalCost={totalCost} />
        </div>
        <div className="card">
          <AllocationDonut
            byHolding={byHolding}
            bySector={bySector}
            unpricedCount={data.rollups.unpriced_position_count}
          />
        </div>
      </div>

      <div
        className="card"
        style={{ display: "grid", gap: "var(--s5)", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}
      >
        <Stat label="Cost" value={formatMagnitude(totalCost)} />
        <Stat
          label="Unrealised P&L"
          value={
            totalGain !== null ? (
              <span className={`delta delta-${directionOf(totalGain)}`}>
                {totalGain >= 0 ? "+" : ""}
                {formatMagnitude(totalGain)}
              </span>
            ) : (
              UNAVAILABLE
            )
          }
          sub={totalGainPct !== null ? <Delta percentage={totalGainPct} /> : undefined}
        />
        <Stat
          label="Realised P&L"
          value={<span className="muted">{UNAVAILABLE}</span>}
          sub={<span className="t-caption muted">Needs a buy/sell transaction log (§41) — not built</span>}
        />
        <Stat
          label="Dividend income (TTM)"
          value={dividend !== null ? formatMagnitude(dividend) : <span className="muted">{UNAVAILABLE}</span>}
          sub={
            <span className="t-caption muted">
              {dividend !== null
                ? `${data.rollups.dividend_positions_counted} holding${data.rollups.dividend_positions_counted === 1 ? "" : "s"}, confirmed cash dividends`
                : "No confirmed cash dividend on a held name in the trailing year"}
            </span>
          }
        />
        <Stat
          label="Portfolio beta"
          value={beta !== null ? beta.toFixed(2) : <span className="muted">{UNAVAILABLE}</span>}
          sub={
            <span className="t-caption muted">
              {beta !== null
                ? betaCoverage >= 99.5
                  ? "whole book"
                  : `${betaCoverage.toFixed(0)}% of value covered`
                : "no holding has a computable beta yet"}
            </span>
          }
        />
        <Stat
          label="Top-3 concentration"
          value={top3Pct !== null ? `${top3Pct.toFixed(0)}%` : <span className="muted">{UNAVAILABLE}</span>}
          sub={
            top3Pct !== null && top3Pct >= 50 ? (
              <span className="t-caption" style={{ color: "var(--caution)" }}>high</span>
            ) : undefined
          }
        />
      </div>

      <div className="card">
        <ZoneDistributionBar zones={data.positions.map((p) => p.price_ladder_zone)} />
      </div>

      {data.positions_missing_a_live_price.length > 0 && (
        <div className="notice notice-caution" role="status">
          <h3>
            {data.positions_missing_a_live_price.length} position
            {data.positions_missing_a_live_price.length === 1 ? "" : "s"} missing a live price
          </h3>
          <p className="prose t-body">
            {data.positions_missing_a_live_price.join(", ")} — no real price history as of {data.as_of},
            so the totals above exclude {data.positions_missing_a_live_price.length === 1 ? "its" : "their"}{" "}
            contribution rather than guessing.
          </p>
        </div>
      )}

      <section aria-labelledby="positions-heading" className="stack-tight">
        <h2 id="positions-heading">Positions ({data.positions.length})</h2>
        <div className="table-wrap table-scroll table-scroll--pinned">
          <table className="data-table">
            <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
              As of {data.as_of}. Fair value, zone and the exit plan come from this system's own real
              valuation engine (§16–26) — a blank cell means the engine doesn't yet have what it needs
              for that name, never a guess. Sorted by nearest exit-plan trigger, not unrealised P&L.
              Open a row (⌄) for its signals, overvaluation and exit prices.
            </caption>
            <thead>
              <tr>
                <th scope="col">Ticker</th>
                <th scope="col" className="right">Qty</th>
                <th scope="col" className="right">Avg</th>
                <th scope="col" className="right">Live</th>
                <th scope="col" className="right">Value</th>
                <th scope="col" className="right">Unrealised P&L</th>
                <th scope="col">12-wk</th>
                <th scope="col" className="right">Fair value</th>
                <th scope="col">Zone</th>
                <th scope="col">Nearest trigger</th>
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

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div>
      <span className="t-label">{label}</span>
      <div className="hero-value" style={{ fontSize: 20 }}>{value}</div>
      {sub && <div style={{ marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/** Small centre-anchored bar: red to the left of centre, green to the
 * right, width ∝ |return|, capped. Turns a column you read into one you
 * scan — an outlier (−34%) jumps out without reading every row. Colour
 * is not the only carrier: the % text with its sign sits right beside
 * it. */
function PnlBar({ pct }: { pct: number }) {
  const capped = Math.max(-40, Math.min(40, pct));
  const half = Math.abs(capped) / 40 / 2; // fraction of full width, each side max 50%
  return (
    <span
      aria-hidden
      style={{ position: "relative", display: "inline-block", width: 48, height: 8, background: "var(--surface-sunken)", borderRadius: 2, verticalAlign: "middle" }}
    >
      <span style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "var(--border-strong)" }} />
      <span
        style={{
          position: "absolute",
          top: 1,
          bottom: 1,
          background: pct >= 0 ? "var(--pos)" : "var(--neg)",
          ...(pct >= 0 ? { left: "50%", width: `${half * 100}%` } : { right: "50%", width: `${half * 100}%` }),
          borderRadius: 1,
        }}
      />
    </span>
  );
}

function PositionRow({ p, onOpen }: { p: ValuedPosition; onOpen: (ticker: string) => void }) {
  const [open, setOpen] = useState(false);
  const gain = p.live_unrealized_gain_loss !== null ? Number(p.live_unrealized_gain_loss) : null;
  const gainPct = gain !== null && Number(p.total_cost) !== 0 ? (gain / Number(p.total_cost)) * 100 : null;
  const spark = p.sparkline.map(Number);
  const hasDetail =
    p.attention_flags.length > 0 ||
    p.warnings.length > 0 ||
    p.decision_verdict !== null ||
    p.overvaluation_pct !== null ||
    p.trim_above_price !== null ||
    p.sell_above_price !== null;

  return (
    <>
      <tr>
        <th scope="row" style={rowHeadStyle}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--s1)" }}>
            {hasDetail && (
              <button
                className="btn-link"
                aria-expanded={open}
                aria-label={open ? `Hide ${p.ticker} signals` : `Show ${p.ticker} signals`}
                onClick={() => setOpen((o) => !o)}
                style={{ fontFamily: "var(--font-mono)", color: "var(--ink-3)", width: "1.2em" }}
              >
                {open ? "⌄" : "›"}
              </button>
            )}
            <button className="btn-link mono" onClick={() => onOpen(p.ticker)}>
              {p.ticker}
            </button>
            {p.thesis_status === "weakening" && (
              <span
                className="chip"
                title={p.attention_flags.map((f) => f.detail).join(" ")}
                style={{ borderColor: "var(--caution)", color: "var(--caution)" }}
              >
                Weakening
              </span>
            )}
          </span>
        </th>
        <td className="right num">{p.quantity}</td>
        <td className="right num">{formatPrice(p.avg_price)}</td>
        <td className="right num">{p.live_current_price !== null ? formatPrice(p.live_current_price) : UNAVAILABLE}</td>
        <td className="right num">{p.live_market_value !== null ? formatPrice(p.live_market_value) : UNAVAILABLE}</td>
        <td className="right">
          {gainPct !== null ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--s2)", justifyContent: "flex-end" }}>
              <PnlBar pct={gainPct} />
              <Delta percentage={gainPct} />
            </span>
          ) : (
            <span className="muted">{UNAVAILABLE}</span>
          )}
        </td>
        <td>
          <Sparkline values={spark} label={`${p.ticker} 12-week price trend`} />
        </td>
        <td className="right num">
          {p.price_ladder_zone !== null && p.blended_fair_value_per_share !== null
            ? formatPrice(p.blended_fair_value_per_share)
            : UNAVAILABLE}
        </td>
        <td>
          <ZoneChip zone={p.price_ladder_zone} why={p.warnings.join(" ") || undefined} compact />
        </td>
        <td>
          {p.nearest_trigger_label !== null && p.nearest_trigger_distance_pct !== null ? (
            <span
              className="t-caption"
              title={`${p.nearest_trigger_label} at ${p.nearest_trigger_price !== null ? formatPrice(p.nearest_trigger_price) : UNAVAILABLE}`}
            >
              {p.nearest_trigger_label}{" "}
              <span className="num">
                ({Number(p.nearest_trigger_distance_pct) >= 0 ? "+" : ""}
                {(Number(p.nearest_trigger_distance_pct) * 100).toFixed(0)}%)
              </span>
            </span>
          ) : (
            <span className="muted">{UNAVAILABLE}</span>
          )}
        </td>
      </tr>
      {open && hasDetail && (
        <tr>
          <td colSpan={10} style={{ background: "var(--surface-sunken)", padding: "var(--s3) var(--s4)" }}>
            <PositionDetail p={p} />
          </td>
        </tr>
      )}
    </>
  );
}

function PositionDetail({ p }: { p: ValuedPosition }) {
  const overvaluation = p.overvaluation_pct !== null ? Number(p.overvaluation_pct) : null;
  return (
    <div style={{ display: "grid", gap: "var(--s3)" }}>
      <div style={{ display: "flex", gap: "var(--s6)", flexWrap: "wrap" }}>
        {p.decision_verdict && (
          <span className="t-caption">
            <span className="t-label">Decision</span>
            <br />
            {p.decision_verdict}
            {p.decision_confidence ? ` · ${p.decision_confidence} confidence` : ""}
          </span>
        )}
        {overvaluation !== null && (
          <span className="t-caption">
            <span className="t-label">Vs. fair value</span>
            <br />
            {Math.abs(overvaluation * 100).toFixed(0)}% {overvaluation >= 0 ? "above" : "below"} fair value
          </span>
        )}
        {p.trim_above_price !== null && (
          <span className="t-caption">
            <span className="t-label">Trim above</span>
            <br />
            {formatPrice(p.trim_above_price)}
          </span>
        )}
        {p.sell_above_price !== null && (
          <span className="t-caption">
            <span className="t-label">Sell above</span>
            <br />
            {formatPrice(p.sell_above_price)}
          </span>
        )}
      </div>

      {p.attention_flags.length > 0 && (
        <div>
          <span className="t-label">Attention flags</span>
          <ul style={{ margin: "var(--s1) 0 0", paddingLeft: "var(--s4)" }}>
            {p.attention_flags.map((f) => (
              <li key={f.key} className="t-caption">
                <strong>{f.label}</strong> — {f.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {p.warnings.length > 0 && (
        <p className="t-caption muted" style={{ margin: 0 }}>{p.warnings.join(" ")}</p>
      )}
    </div>
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
