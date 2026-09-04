import { useState } from "react";
import { Delta } from "./Delta";
import { formatIndexValue, formatMagnitude } from "../format";
import type { SectorSnapshot } from "../types";

/**
 * Macro page redesign spec §4 chart #4 — sector indices as a sorted
 * diverging bar chart instead of a 21-row plain table. Same visual
 * language as `SectorValueBars` (the homepage's median-discount bars):
 * a diverging bar centred on zero, `--pos`/`--neg` by sign, every bar
 * still carrying its own signed label so colour is never the sole
 * carrier of meaning (§17). Sorted by today's % change, gainers first —
 * the order that answers "what actually moved" without reading all 21
 * rows.
 *
 * The full table (index level, turnover) stays one click away behind a
 * "View as table" toggle, per the spec's "every chart ships with a
 * view-as-table toggle" rule — nothing here removes data the plain
 * table already showed, it's a second way to read the same rows.
 */
export function SectorPerformanceBars({
  sectors,
  onSelectSector,
}: {
  sectors: SectorSnapshot[];
  onSelectSector: (sector: string) => void;
}) {
  const [asTable, setAsTable] = useState(false);

  const ranked = [...sectors]
    .filter((s) => s.percentage !== null)
    .sort((a, b) => (b.percentage ?? 0) - (a.percentage ?? 0));

  const maxAbs = Math.max(...ranked.map((s) => Math.abs(s.percentage ?? 0)), 0.5);

  return (
    <div className="stack-tight">
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button className="btn-link t-caption" onClick={() => setAsTable((v) => !v)}>
          {asTable ? "View as chart" : "View as table"}
        </button>
      </div>

      {asTable ? (
        <div className="table-wrap table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Sector</th>
                <th scope="col" className="right">Index</th>
                <th scope="col" className="right">Change</th>
                <th scope="col" className="right">Turnover today (LKR)</th>
              </tr>
            </thead>
            <tbody>
              {sectors.map((s) => (
                <tr key={s.name}>
                  <th scope="row" style={rowHeadStyle}>
                    <button className="btn-link" onClick={() => onSelectSector(s.name)}>
                      {s.name}
                    </button>
                  </th>
                  <td className="right num">{formatIndexValue(s.index_value)}</td>
                  <td className="right">
                    <Delta percentage={s.percentage} />
                  </td>
                  <td className="right num">{formatMagnitude(s.turnover_today)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <figure style={{ margin: 0 }}>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--s2)" }}>
            {ranked.map((s) => {
              const v = s.percentage ?? 0;
              const positive = v > 0;
              const halfPct = (Math.abs(v) / maxAbs) * 50;
              return (
                <li
                  key={s.name}
                  style={{ display: "grid", gridTemplateColumns: "150px 1fr 70px", alignItems: "center", gap: "var(--s3)" }}
                >
                  <button
                    className="btn-link"
                    onClick={() => onSelectSector(s.name)}
                    style={{ textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  >
                    {s.name}
                  </button>
                  <span
                    aria-hidden
                    style={{ position: "relative", height: 12, background: "var(--surface-sunken)", borderRadius: 2 }}
                  >
                    <span style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "var(--border-strong)" }} />
                    <span
                      style={{
                        position: "absolute",
                        top: 1,
                        bottom: 1,
                        borderRadius: 2,
                        background: positive ? "var(--pos)" : v < 0 ? "var(--neg)" : "var(--ink-4)",
                        ...(v >= 0
                          ? { left: "50%", width: `${halfPct}%` }
                          : { right: "50%", width: `${halfPct}%` }),
                      }}
                    />
                  </span>
                  <span style={{ textAlign: "right" }}>
                    <Delta percentage={v} />
                  </span>
                </li>
              );
            })}
          </ul>
          <figcaption className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
            Today's % change per S&amp;P/CSE industry-group index, sorted gainers first. Bar length
            is relative to the largest move on this board today.
          </figcaption>
        </figure>
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
