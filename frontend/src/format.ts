/**
 * UI & Experience Specification §5.1 — number display conventions.
 *
 * The rule that matters most here: a null is rendered as "Data
 * unavailable", never as a dash, never as a zero, never omitted (§5.1,
 * and anti-pattern "Hiding missing data"). Every formatter below returns
 * the UNAVAILABLE sentinel rather than an empty string or "0" so a caller
 * physically cannot render a gap as if it were a value.
 */

export const UNAVAILABLE = "Data unavailable";

/** LKR prices: two decimals, thousands separated (§5.1). */
export function formatPrice(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return UNAVAILABLE;
  const n = Number(value);
  if (!Number.isFinite(n)) return UNAVAILABLE;
  return n.toLocaleString("en-LK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * Large magnitudes: "LKR 7.68tn · 412bn · 1.4bn · 860m — never a wall of
 * digits" (§5.1).
 */
export function formatMagnitude(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return UNAVAILABLE;
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return UNAVAILABLE;
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}tn`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}bn`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}m`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return n.toLocaleString("en-LK", { maximumFractionDigits: 0 });
}

/** Percentages: one decimal (§5.1). Sign is always explicit. */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNAVAILABLE;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

export function formatIndexValue(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNAVAILABLE;
  return value.toLocaleString("en-LK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNAVAILABLE;
  return value.toLocaleString("en-LK");
}

export type Direction = "up" | "down" | "flat" | "unknown";

export function directionOf(value: number | null | undefined): Direction {
  if (value === null || value === undefined || !Number.isFinite(value)) return "unknown";
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

/**
 * §5.2 — direction is carried by THREE signals at once: hue, lightness
 * and a glyph. This returns the glyph so colour is never the sole
 * carrier of meaning (a hard accessibility requirement, §2.5/§15.2).
 */
export function directionGlyph(direction: Direction): string {
  switch (direction) {
    case "up":
      return "▲";
    case "down":
      return "▼";
    case "flat":
      return "—";
    default:
      return "";
  }
}

/**
 * "2m ago" / "3d ago" — the sidebar DATA section's own freshness dots
 * (P1.1) need this compactly, unlike every other screen's full
 * `toLocaleString()` timestamp. Coarsens deliberately: once something is
 * more than a day old, the exact minute stops being the useful unit.
 */
export function formatAgo(iso: string | null | undefined): string {
  if (!iso) return UNAVAILABLE;
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return UNAVAILABLE;
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
