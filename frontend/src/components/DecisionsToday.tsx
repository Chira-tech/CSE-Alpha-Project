import type { ReactNode } from "react";

/**
 * Homepage redesign §6: "'3 decisions today' is the hero, not a market
 * summary. The product exists to tell you when price is wrong. That
 * belongs above everything else. Most days it will be empty — 'Nothing
 * needs a decision today' is a legitimate and valuable answer, and it
 * should feel calm rather than broken."
 *
 * The items are the `/composite-ranking` `insights` — plain factual
 * sentences, each backed by a real delta between two scheduled runs
 * (verdict transitions, big score movers, sector shifts). They are
 * empty until a second run exists to diff against, and the empty state
 * says exactly that rather than implying a quiet day it can't verify.
 * Any ticker mentioned in a sentence is turned into a button through to
 * its company file.
 */
function linkify(sentence: string, tickers: Set<string>, onOpen: (t: string) => void): ReactNode[] {
  return sentence.split(/(\s+)/).map((token, i) => {
    const bare = token.replace(/[.,:;]+$/, "");
    if (tickers.has(bare)) {
      const trailing = token.slice(bare.length);
      return (
        <span key={i}>
          <button className="btn-link" onClick={() => onOpen(bare)}>
            {bare}
          </button>
          {trailing}
        </span>
      );
    }
    return <span key={i}>{token}</span>;
  });
}

export function DecisionsToday({
  insights,
  tickers,
  onOpen,
  historyAvailable,
}: {
  insights: string[];
  tickers: Set<string>;
  onOpen: (ticker: string) => void;
  /** `false` when only one scheduled run exists — there is nothing to
   * diff against yet, which is different from "a genuinely quiet day". */
  historyAvailable: boolean;
}) {
  if (insights.length === 0) {
    return (
      <div className="notice notice-neutral">
        <h3>Nothing needs a decision today</h3>
        <p className="prose t-body">
          {historyAvailable
            ? "No verdict changed, no composite score moved materially, and no sector re-rated since the last scheduled run. A 12–36 month strategy should read like this on most days."
            : "Decision history starts once there is more than one scheduled run to compare — the first run has nothing to measure change against yet."}
        </p>
      </div>
    );
  }

  return (
    <ul className="decisions-list">
      {insights.map((sentence, i) => (
        <li key={i} className="t-body">
          {linkify(sentence, tickers, onOpen)}
        </li>
      ))}
    </ul>
  );
}
