import { useState } from "react";
import { CorporateActionsQueue } from "../components/CorporateActionsQueue";
import { FundamentalsQueue } from "../components/FundamentalsQueue";

export function ReviewScreen({
  reviewerName,
  onChangeReviewerName,
  onBack,
}: {
  reviewerName: string;
  onChangeReviewerName: (value: string) => void;
  onBack: () => void;
}) {
  const [tab, setTab] = useState<"corporate-actions" | "fundamentals">("corporate-actions");

  return (
    <div className="route stack">
      <button className="btn-link" onClick={onBack}>
        ← Data health
      </button>

      <header className="screen-head spread">
        <div>
          <h1>Confirm queue</h1>
          <p className="prose">
            Master Spec §5 — every scraped corporate action and every AI-assisted financial figure
            waits here until a human confirms it. Nothing below has affected any price or valuation.
          </p>
        </div>
        <div className="field">
          <label htmlFor="reviewer" className="t-label">
            Reviewing as
          </label>
          <input
            id="reviewer"
            type="text"
            placeholder="your name"
            value={reviewerName}
            onChange={(e) => onChangeReviewerName(e.target.value)}
            style={{ width: 180 }}
          />
        </div>
      </header>

      <div className="subtabs" role="group" aria-label="Queue type">
        <button
          className="subtab"
          aria-pressed={tab === "corporate-actions"}
          onClick={() => setTab("corporate-actions")}
        >
          Corporate actions
        </button>
        <button
          className="subtab"
          aria-pressed={tab === "fundamentals"}
          onClick={() => setTab("fundamentals")}
        >
          Fundamentals
        </button>
      </div>

      {tab === "corporate-actions" ? (
        <CorporateActionsQueue reviewerName={reviewerName} />
      ) : (
        <FundamentalsQueue reviewerName={reviewerName} />
      )}
    </div>
  );
}
