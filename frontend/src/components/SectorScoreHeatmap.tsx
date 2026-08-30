import { ScoreBar } from "./ScoreBar";

/**
 * Average composite score by CSE sector — the redesign doc's §1.2 "which
 * sectors are becoming attractive" read. A per-category mean is the one
 * comparison a score-sorted table genuinely can't do at a glance, so
 * this is the chart that earns its place on the page.
 *
 * Rendered as a sorted mean-bar list rather than a colour grid: with ~20
 * CSE sectors a grid of tinted cells is harder to read than bars you can
 * line up, and it keeps the same `ScoreBar` mark the rows below use, so
 * the page reads as one system. Sectors with only one ranked name are
 * shown but flagged — a "sector average" of one company isn't one.
 */
export interface SectorScore {
  sector: string;
  mean: number;
  count: number;
}

export function sectorScores(
  rows: { cse_sector: string | null; total_score: string | null }[],
): SectorScore[] {
  const byS = new Map<string, number[]>();
  for (const r of rows) {
    if (!r.cse_sector || r.total_score === null) continue;
    const arr = byS.get(r.cse_sector) ?? [];
    arr.push(Number(r.total_score));
    byS.set(r.cse_sector, arr);
  }
  return [...byS.entries()]
    .map(([sector, xs]) => ({ sector, mean: xs.reduce((a, b) => a + b, 0) / xs.length, count: xs.length }))
    .sort((a, b) => b.mean - a.mean);
}

export function SectorScoreHeatmap({
  rows,
}: {
  rows: { cse_sector: string | null; total_score: string | null }[];
}) {
  const scores = sectorScores(rows);
  if (scores.length === 0) return null;

  return (
    <figure style={{ margin: 0, display: "grid", gap: "var(--s2)" }}>
      <figcaption className="t-label">Average score by sector</figcaption>
      <div style={{ display: "grid", gap: "var(--s1)" }}>
        {scores.map((s) => (
          <div
            key={s.sector}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 10rem) 1fr auto",
              alignItems: "center",
              gap: "var(--s2)",
            }}
          >
            <span className="t-caption" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {s.sector}
            </span>
            <ScoreBar score={s.mean} compact width={160} />
            <span className="t-caption num" style={{ color: "var(--ink-3)" }}>
              {Math.round(s.mean)}
              {s.count === 1 ? <span title="only one ranked name in this sector"> ·1</span> : ` ·${s.count}`}
            </span>
          </div>
        ))}
      </div>
    </figure>
  );
}
