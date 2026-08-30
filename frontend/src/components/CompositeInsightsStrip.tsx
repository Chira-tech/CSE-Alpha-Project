/**
 * The Top Insights strip above the scoreboard — the redesign doc's §0.4
 * / §1.2. It answers "what actually changed since last week" so the
 * table below is there to verify or go deeper, not as the only way in.
 *
 * Every sentence is computed on the backend from a real diff between two
 * real snapshots (`app.domain.composite_ranking_snapshot_view.build_
 * insights`) — verdict transitions, big score movers on well-
 * corroborated rows, sector-average shifts. Nothing here is generated
 * prose or a recommendation to trade.
 *
 * When there is no ~week-old snapshot yet, `insights` is empty and this
 * shows an honest note rather than inventing movement.
 */
export function CompositeInsightsStrip({
  insights,
  snapshotAvailable,
}: {
  insights: string[];
  snapshotAvailable: boolean;
}) {
  if (insights.length === 0) {
    return (
      <p className="t-caption muted" style={{ margin: 0 }}>
        {snapshotAvailable
          ? "Week-over-week insights appear once two scheduled snapshots a week apart exist."
          : "Week-over-week insights appear once the scoreboard runs on its schedule."}
      </p>
    );
  }

  return (
    <section
      aria-labelledby="composite-insights-heading"
      className="notice notice-neutral"
      style={{ display: "grid", gap: "var(--s2)" }}
    >
      <h3 id="composite-insights-heading" style={{ margin: 0 }}>
        Since last week
      </h3>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--s1)" }}>
        {insights.map((line) => (
          <li key={line} className="t-body prose">
            • {line}
          </li>
        ))}
      </ul>
      <p className="t-caption muted" style={{ margin: 0 }}>
        Real deltas between two scheduled snapshots — not a recommendation to trade.
      </p>
    </section>
  );
}
