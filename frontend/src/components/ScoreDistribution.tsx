/**
 * The spread of composite scores across the ranked board, in ten
 * fixed 0-100 buckets. The redesign doc (§1.2) calls for a distribution
 * histogram here because "is the whole board mediocre, or is there a
 * cluster of genuinely strong names" is a shape question a sorted table
 * answers only by scrolling.
 *
 * Same inline-SVG, no-library, theme-token idiom as `Sparkline` /
 * `PriceHistoryChart`. Zero-based on the count axis (a count of zero IS
 * meaningful, unlike a share price), and the bucket edges are labelled
 * so the mark is never the only source of the numbers.
 */
export function ScoreDistribution({ scores }: { scores: number[] }) {
  const clean = scores.filter((s) => Number.isFinite(s));
  if (clean.length === 0) return null;

  const buckets = Array.from({ length: 10 }, () => 0);
  for (const s of clean) {
    const idx = Math.min(9, Math.max(0, Math.floor(s / 10)));
    buckets[idx] += 1;
  }
  const maxCount = Math.max(...buckets, 1);

  const W = 320;
  const H = 96;
  const gap = 3;
  const barW = (W - gap * 9) / 10;

  return (
    <figure style={{ margin: 0, display: "grid", gap: "var(--s2)" }}>
      <figcaption className="t-label">Score distribution ({clean.length} ranked)</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="histogram of composite scores in bands of ten" style={{ maxWidth: W }}>
        {buckets.map((count, i) => {
          const h = (count / maxCount) * (H - 18);
          return (
            <g key={i}>
              <rect
                x={i * (barW + gap)}
                y={H - 14 - h}
                width={barW}
                height={h}
                fill="var(--brand-500)"
                rx="1.5"
              />
              <text
                x={i * (barW + gap) + barW / 2}
                y={H - 3}
                textAnchor="middle"
                fontSize="7"
                fill="var(--ink-3)"
              >
                {i * 10}
              </text>
              {count > 0 && (
                <text
                  x={i * (barW + gap) + barW / 2}
                  y={H - 18 - h}
                  textAnchor="middle"
                  fontSize="7"
                  fill="var(--ink-3)"
                >
                  {count}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
