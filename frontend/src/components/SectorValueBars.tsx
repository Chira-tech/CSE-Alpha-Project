import { useMemo } from "react";
import type { RankedComposite } from "../types";
import { directionGlyph } from "../format";

/**
 * Homepage redesign §6: "median discount to fair value" by sector —
 * "Banks -22%, LFC -17%, Hotels +4% (premium)".
 *
 * Form per the `dataviz` heuristic: the data has POLARITY (cheap vs
 * expensive), so a diverging bar centred on zero — cheap extends one
 * way in `--pos`, premium the other in `--neg`, with a neutral zero
 * rule. Never a rainbow, never a hue at the midpoint. Each row is
 * labelled with its sector, a direction glyph and the signed number, so
 * the sign is never carried by colour alone. Sectors are ordered by
 * median discount, cheapest first — the reading order the section title
 * asks for.
 */
function discountOf(row: RankedComposite): number | null {
  const d = row.discount_to_fair_value_pct;
  if (d === null) return null;
  const n = Number(d);
  return Number.isFinite(n) ? n : null;
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor((s.length - 1) / 2)];
}

export function SectorValueBars({
  rows,
  minCompanies = 3,
}: {
  rows: RankedComposite[];
  /** A sector needs at least this many priced companies for a median
   * to mean anything — below it the sector is dropped, not shown thin. */
  minCompanies?: number;
}) {
  const sectors = useMemo(() => {
    const bySector = new Map<string, number[]>();
    for (const r of rows) {
      const s = r.cse_sector;
      const d = discountOf(r);
      if (!s || d === null) continue;
      const bucket = bySector.get(s);
      if (bucket) bucket.push(d);
      else bySector.set(s, [d]);
    }
    return [...bySector.entries()]
      .filter(([, ds]) => ds.length >= minCompanies)
      .map(([sector, ds]) => ({ sector, med: median(ds), n: ds.length }))
      .sort((a, b) => b.med - a.med);
  }, [rows, minCompanies]);

  if (sectors.length === 0) {
    return (
      <p className="t-caption prose">
        No sector has {minCompanies}+ companies with a discount-to-fair-value in the latest run yet.
      </p>
    );
  }

  const maxAbs = Math.max(...sectors.map((s) => Math.abs(s.med)), 0.05);

  return (
    <figure style={{ margin: 0 }}>
      <ul
        style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--s2)" }}
      >
        {sectors.map(({ sector, med, n }) => {
          const cheap = med > 0;
          const glyph = directionGlyph(cheap ? "up" : med < 0 ? "down" : "flat");
          const halfPct = (Math.abs(med) / maxAbs) * 50;
          return (
            <li key={sector} style={{ display: "grid", gridTemplateColumns: "150px 1fr 74px", alignItems: "center", gap: "var(--s3)" }}>
              <span style={{ color: "var(--ink-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {sector}{" "}
                <span className="num" style={{ color: "var(--ink-4)" }}>
                  {n}
                </span>
              </span>
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
                    background: cheap ? "var(--pos)" : "var(--neg)",
                    ...(cheap
                      ? { left: "50%", width: `${halfPct}%` }
                      : { right: "50%", width: `${halfPct}%` }),
                  }}
                />
              </span>
              <span className="num" style={{ textAlign: "right", color: "var(--ink-2)", fontWeight: 500 }}>
                {glyph} {med >= 0 ? "+" : "−"}
                {(Math.abs(med) * 100).toFixed(0)}%
              </span>
            </li>
          );
        })}
      </ul>
      <figcaption className="t-caption prose" style={{ marginTop: "var(--s3)" }}>
        Median (price − fair value) ÷ fair value per sector, sectors with {minCompanies}+ priced
        companies only. A positive figure is a discount to fair value; a negative one is a premium.
      </figcaption>
    </figure>
  );
}
