#!/usr/bin/env node
/**
 * TASK 0.2's own CI grep guard: "no component may render
 * `zone ?? 'Fair'` or any default-substitution on a valuation field."
 *
 * WHY THIS EXISTS. `PriceLadderOut.current_zone` and every other
 * derived-from-a-fair-value field this app displays (`fair_value`,
 * `buy_below_price`, `blended_fair_value_per_share`, ...) is
 * `Optional[str]`/`| null` for a real reason (§1 law 3: never
 * substitute a default for a missing valuation field) — TASK 0.1's own
 * plausibility gate is proof that "null" here specifically means
 * "withheld, on purpose, because a wrong number is worse than no
 * number." A single `zone ?? 'fair'` anywhere would silently defeat
 * that gate for a reader who never sees a real value at all.
 *
 * This is a real static check, not a formality: it scans every
 * `.ts`/`.tsx` file under `src/` for a nullish-coalescing (`??`) or
 * logical-OR (`||`) fallback applied directly to one of the named
 * valuation fields, immediately followed by a string or numeric
 * literal — the exact shape of a silent default substitution.
 *
 * Run via `npm run check:zone-fallback` (also part of `npm run lint`,
 * the closest thing this project has to a CI gate today — see
 * package.json).
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC_DIR = fileURLToPath(new URL("../src", import.meta.url));

// The fields TASK 0.1/0.2 make it dangerous to default-substitute —
// every one of them is null specifically to mean "withheld," never
// "unset, so assume a safe value."
const GUARDED_FIELDS = [
  "zone",
  "current_zone",
  "price_ladder_zone",
  "fair_value",
  "blended_fair_value_per_share",
  "buy_below_price",
  "price_ladder",
];

// Matches e.g. `zone ?? 'fair'`, `p.current_zone || "Fair"`,
// `blended_fair_value_per_share ?? 0` — a guarded field name directly
// followed by `??`/`||` and a string or numeric literal fallback.
const FIELD_ALTERNATION = GUARDED_FIELDS.map((f) => f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
const PATTERN = new RegExp(`\\b(?:${FIELD_ALTERNATION})\\b\\s*(?:\\?\\?|\\|\\|)\\s*(['"\`]|\\d)`);

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (entry === "node_modules" || entry === "dist") continue;
      yield* walk(full);
    } else if (/\.(ts|tsx)$/.test(entry)) {
      yield full;
    }
  }
}

let violations = [];
for (const file of walk(SRC_DIR)) {
  const lines = readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    if (PATTERN.test(line)) {
      violations.push({ file, line: i + 1, text: line.trim() });
    }
  });
}

if (violations.length > 0) {
  console.error("TASK 0.2 CI guard failed — default-substitution found on a valuation field:\n");
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line}: ${v.text}`);
  }
  console.error(
    "\nA valuation field (zone, fair_value, buy_below_price, ...) must never fall back to a " +
      "literal — null means \"withheld,\" not \"unset.\" Show the real reason instead (see " +
      "ZoneChip's `why` prop / NOT_YET_VALUED)."
  );
  process.exit(1);
}

console.log(`TASK 0.2 CI guard passed — no default-substitution found on a valuation field (${GUARDED_FIELDS.length} fields checked).`);
