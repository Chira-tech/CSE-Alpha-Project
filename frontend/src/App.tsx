import { useState } from "react";
import { CorporateActionsQueue } from "./components/CorporateActionsQueue";
import { FundamentalsQueue } from "./components/FundamentalsQueue";
import { useReviewerName } from "./hooks/useReviewerName";

type Tab = "corporate-actions" | "fundamentals";

export function App() {
  const [tab, setTab] = useState<Tab>("corporate-actions");
  const { name, setName } = useReviewerName();

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>Confirm queue</h1>
          <p className="subtitle">
            Master Spec §5 — every scraped corporate action and every AI-assisted financial figure
            waits here until a human confirms it. Nothing below has affected any price or valuation
            yet.
          </p>
        </div>
        <label className="reviewer-field">
          <span>Reviewing as</span>
          <input
            type="text"
            placeholder="your name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
      </header>

      <nav className="tabs">
        <button
          type="button"
          className={tab === "corporate-actions" ? "tab tab-active" : "tab"}
          onClick={() => setTab("corporate-actions")}
        >
          Corporate actions
        </button>
        <button
          type="button"
          className={tab === "fundamentals" ? "tab tab-active" : "tab"}
          onClick={() => setTab("fundamentals")}
        >
          Fundamentals
        </button>
      </nav>

      <main>
        {tab === "corporate-actions" ? (
          <CorporateActionsQueue reviewerName={name} />
        ) : (
          <FundamentalsQueue reviewerName={name} />
        )}
      </main>
    </div>
  );
}
