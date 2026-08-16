import { useState } from "react";
import { CorporateActionsQueue } from "./components/CorporateActionsQueue";
import { FundamentalsQueue } from "./components/FundamentalsQueue";
import { useReviewerName } from "./hooks/useReviewerName";
import { CompaniesScreen } from "./screens/CompaniesScreen";
import { CompanyScreen } from "./screens/CompanyScreen";
import { DataHealthScreen } from "./screens/DataHealthScreen";
import { MarketScreen } from "./screens/MarketScreen";

type Screen = "market" | "companies" | "review" | "health";

const NAV: { id: Screen; label: string; blurb: string }[] = [
  { id: "market", label: "Market", blurb: "Where the exchange is right now" },
  { id: "companies", label: "Companies", blurb: "Every listed name" },
  { id: "review", label: "Review queue", blurb: "Data awaiting human confirmation" },
  { id: "health", label: "Data health", blurb: "Coverage, freshness, quarantine" },
];

export function App() {
  const [screen, setScreen] = useState<Screen>("market");
  const [openTicker, setOpenTicker] = useState<string | null>(null);
  const [reviewTab, setReviewTab] = useState<"corporate-actions" | "fundamentals">(
    "corporate-actions",
  );
  const { name, setName } = useReviewerName();

  function go(next: Screen) {
    setScreen(next);
    setOpenTicker(null);
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>CSE Alpha Engine</h1>
          <p className="subtitle">
            Phase 1 — the point-in-time data spine. What you can see here is real data from the
            Colombo Stock Exchange. What you can't see yet — fair values, scores, buy prices — is
            listed plainly rather than faked.
          </p>
        </div>
        {screen === "review" && (
          <label className="reviewer-field">
            <span>Reviewing as</span>
            <input
              type="text"
              placeholder="your name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        )}
      </header>

      <nav className="tabs">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            title={item.blurb}
            className={screen === item.id ? "tab tab-active" : "tab"}
            onClick={() => go(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <main>
        {screen === "market" && <MarketScreen />}

        {screen === "companies" &&
          (openTicker ? (
            <CompanyScreen ticker={openTicker} onBack={() => setOpenTicker(null)} />
          ) : (
            <CompaniesScreen onOpen={setOpenTicker} />
          ))}

        {screen === "review" && (
          <div className="stack">
            <div className="subtabs">
              <button
                type="button"
                className={reviewTab === "corporate-actions" ? "subtab subtab-active" : "subtab"}
                onClick={() => setReviewTab("corporate-actions")}
              >
                Corporate actions
              </button>
              <button
                type="button"
                className={reviewTab === "fundamentals" ? "subtab subtab-active" : "subtab"}
                onClick={() => setReviewTab("fundamentals")}
              >
                Fundamentals
              </button>
            </div>
            <p className="provenance-note">
              Master Spec §5 — every scraped corporate action and every AI-assisted financial figure
              waits here until a human confirms it. Nothing below has affected any price or valuation.
            </p>
            {reviewTab === "corporate-actions" ? (
              <CorporateActionsQueue reviewerName={name} />
            ) : (
              <FundamentalsQueue reviewerName={name} />
            )}
          </div>
        )}

        {screen === "health" && <DataHealthScreen />}
      </main>
    </div>
  );
}
