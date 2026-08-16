import type { NavItem } from "../nav";

/**
 * The honest destination for a nav item whose engines don't exist yet.
 *
 * This exists instead of either hiding the destination (which would
 * misrepresent the product's shape) or filling it with sample content
 * (the §17 anti-pattern: "Placeholder or lorem content in any shipped
 * state — in a financial product, a fake number that reaches a user once
 * destroys trust permanently").
 */
export function NotBuiltScreen({ item }: { item: NavItem }) {
  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>{item.label}</h1>
        <p className="prose">{item.blurb}</p>
      </header>

      <div className="notice notice-neutral">
        <h3>Not built yet — {item.awaitingPhase}</h3>
        <p className="prose t-body">{item.willContain}</p>
        <p className="prose t-body">
          Nothing is shown here rather than sample numbers: in a system whose whole purpose is
          deciding what to pay for a business, a figure that looks real and isn't is worse than no
          figure at all.
        </p>
      </div>
    </div>
  );
}
