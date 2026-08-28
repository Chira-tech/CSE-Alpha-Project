/**
 * R1 T4.6.4 — "market share is a part-to-whole relationship, which
 * treemaps encode accurately and radar charts do not." A real
 * squarified treemap (Bruls/Huizing/van Wijk), not a radar/spider
 * chart, per the brief's explicit instruction — area is proportional
 * to each item's own real value, nothing else on the page implies a
 * relationship this algorithm doesn't actually encode.
 */
export interface TreemapItem {
  key: string;
  label: string;
  value: number;
}

interface Rect {
  key: string;
  label: string;
  value: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

function worstRatio(row: number[], length: number): number {
  const sum = row.reduce((a, b) => a + b, 0);
  const max = Math.max(...row);
  const min = Math.min(...row);
  const lenSq = length * length;
  return Math.max((lenSq * max) / (sum * sum), (sum * sum) / (lenSq * min));
}

// `horizontal` names the REMAINING RECTANGLE's shape (w >= h), which
// means the strip laid out here is a VERTICAL column of fixed width
// `thickness` down the left edge, with items stacked top-to-bottom
// inside it — not a horizontal row. (A tall remaining rectangle gets
// the opposite: a horizontal row of fixed height across the top, items
// side by side.) Getting this backwards is what produces overlapping
// rectangles instead of a clean tiling.
function layoutRow(row: number[], length: number, x: number, y: number, horizontal: boolean): Rect[] {
  const sum = row.reduce((a, b) => a + b, 0);
  const thickness = sum / length;
  let offset = 0;
  return row.map((v, i) => {
    const size = thickness > 0 ? v / thickness : 0;
    let rect: Omit<Rect, "key" | "label" | "value">;
    if (horizontal) {
      rect = { x, y: y + offset, w: thickness, h: size };
    } else {
      rect = { x: x + offset, y, w: size, h: thickness };
    }
    offset += size;
    return { key: String(i), label: "", value: v, ...rect };
  });
}

/** Squarify a pre-sorted-descending list of positive values into a
 * `w`x`h` rectangle. Returns rects in the same order as `values`. */
function squarify(values: number[], x: number, y: number, w: number, h: number): Rect[] {
  if (values.length === 0) return [];
  const horizontal = w >= h;
  const length = horizontal ? h : w;

  let row: number[] = [];
  let i = 0;
  const results: Rect[] = [];
  let cx = x, cy = y, cw = w, ch = h;

  while (i < values.length) {
    const next = values[i];
    const candidate = [...row, next];
    if (row.length === 0 || worstRatio(candidate, length) <= worstRatio(row, length)) {
      row = candidate;
      i++;
    } else {
      break;
    }
  }
  const rowRects = layoutRow(row, length, cx, cy, horizontal);
  results.push(...rowRects);

  // Advance the remaining rectangle by the thickness the row consumed.
  const rowThickness = row.length > 0 ? row.reduce((a, b) => a + b, 0) / length : 0;
  if (horizontal) {
    cx += rowThickness;
    cw -= rowThickness;
  } else {
    cy += rowThickness;
    ch -= rowThickness;
  }

  const remaining = values.slice(row.length);
  if (remaining.length > 0 && cw > 0 && ch > 0) {
    results.push(...squarify(remaining, cx, cy, cw, ch));
  }
  return results;
}

export function layoutTreemap(items: TreemapItem[], width: number, height: number): (Rect & { item: TreemapItem })[] {
  const positive = items.filter((it) => it.value > 0);
  const total = positive.reduce((a, b) => a + b.value, 0);
  if (total <= 0) return [];
  const scale = (width * height) / total;
  const values = positive.map((it) => it.value * scale);
  const rects = squarify(values, 0, 0, width, height);
  return rects.map((r, i) => ({ ...r, item: positive[i] }));
}

const PALETTE = ["var(--brand-100)", "var(--brand-200)", "var(--brand-300)", "var(--brand-400)"];

export function Treemap({
  items,
  width = 640,
  height = 320,
  onSelect,
  formatValue,
}: {
  items: TreemapItem[];
  width?: number;
  height?: number;
  onSelect?: (key: string) => void;
  formatValue: (v: number) => string;
}) {
  const rects = layoutTreemap(items, width, height);
  if (rects.length === 0) {
    return <p className="prose t-caption muted">No real, computable values to size this treemap from.</p>;
  }
  return (
    <div style={{ position: "relative", width, height, maxWidth: "100%", border: "1px solid var(--border)" }}>
      {rects.map((r, i) => (
        <button
          key={r.item.key}
          onClick={() => onSelect?.(r.item.key)}
          title={`${r.item.label}: ${formatValue(r.item.value)}`}
          style={{
            position: "absolute",
            left: `${(r.x / width) * 100}%`,
            top: `${(r.y / height) * 100}%`,
            width: `${(r.w / width) * 100}%`,
            height: `${(r.h / height) * 100}%`,
            background: PALETTE[i % PALETTE.length],
            border: "1px solid var(--bg)",
            overflow: "hidden",
            padding: "var(--s1)",
            textAlign: "left",
            cursor: onSelect ? "pointer" : "default",
            color: "var(--ink-1)",
            fontSize: 12,
          }}
        >
          {r.w > 40 && r.h > 20 ? (
            <>
              <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {r.item.label}
              </div>
              <div className="t-caption">{formatValue(r.item.value)}</div>
            </>
          ) : null}
        </button>
      ))}
    </div>
  );
}
