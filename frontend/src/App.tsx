import { useEffect, useState } from "react";
import { useReviewerName } from "./hooks/useReviewerName";
import { NAV_ITEMS, REVIEW_SCREEN, type ScreenId } from "./nav";
import { CompaniesScreen } from "./screens/CompaniesScreen";
import { CompanyScreen } from "./screens/CompanyScreen";
import { DataHealthScreen } from "./screens/DataHealthScreen";
import { MacroScreen } from "./screens/MacroScreen";
import { NotBuiltScreen } from "./screens/NotBuiltScreen";
import { OpportunitiesScreen } from "./screens/OpportunitiesScreen";
import { PortfolioScreen } from "./screens/PortfolioScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { TodayScreen } from "./screens/TodayScreen";

export function App() {
  const [screen, setScreen] = useState<ScreenId>("today");
  const [openTicker, setOpenTicker] = useState<string | null>(null);
  const { name, setName } = useReviewerName();

  function go(next: ScreenId) {
    setScreen(next);
    setOpenTicker(null);
    // Route change moves focus to the main region so keyboard and screen
    // reader users land on the new content rather than staying in the
    // nav (§15.2 logical tab order).
    requestAnimationFrame(() => document.getElementById("main")?.focus());
  }

  // §7.1: "Global search (⌘K) ... is the fastest path to anything."
  // Full command palette is a later screen; for now the shortcut takes
  // you to Companies and focuses its filter, which is the only search
  // surface that exists.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setScreen("companies");
        setOpenTicker(null);
        requestAnimationFrame(() => document.getElementById("company-search")?.focus());
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const primary = NAV_ITEMS.filter((i) => i.group === "primary");
  const advanced = NAV_ITEMS.filter((i) => i.group === "advanced");

  function renderScreen() {
    switch (screen) {
      case "today":
        return <TodayScreen onOpenScreen={(id) => go(id)} />;
      case "companies":
        return openTicker ? (
          <CompanyScreen
            ticker={openTicker}
            onBack={() => setOpenTicker(null)}
            onOpen={setOpenTicker}
          />
        ) : (
          <CompaniesScreen onOpen={setOpenTicker} />
        );
      case "macro":
        return <MacroScreen />;
      case "portfolio":
        return <PortfolioScreen />;
      case "opportunities":
        return <OpportunitiesScreen />;
      case "data-health":
        return <DataHealthScreen onOpenReview={() => go("review")} />;
      case "review":
        return (
          <ReviewScreen
            reviewerName={name}
            onChangeReviewerName={setName}
            onBack={() => go("data-health")}
          />
        );
      default: {
        const item = NAV_ITEMS.find((i) => i.id === screen);
        return item ? <NotBuiltScreen item={item} /> : null;
      }
    }
  }

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <div className="shell">
        <nav className="rail" aria-label="Primary">
          <div className="rail-brand">
            <div className="rail-brand-name">CSE Alpha Engine</div>
            <div className="t-caption">Backend: Phases 1–6 · UI catching up</div>
          </div>

          <div className="rail-search">
            <button
              onClick={() => {
                go("companies");
                requestAnimationFrame(() => document.getElementById("company-search")?.focus());
              }}
              style={{ width: "100%", textAlign: "left", color: "var(--ink-3)" }}
            >
              Search companies… <span className="t-caption">⌘K</span>
            </button>
          </div>

          <div className="rail-nav">
            <div className="rail-group">
              {primary.map((item) => (
                <RailItem key={item.id} item={item} current={screen} onGo={go} />
              ))}
            </div>
            <div className="rail-group">
              {advanced.map((item) => (
                <RailItem key={item.id} item={item} current={screen} onGo={go} />
              ))}
              <RailItem item={REVIEW_SCREEN} current={screen} onGo={go} />
            </div>
          </div>

          <div className="rail-foot">
            <p className="t-caption prose" style={{ margin: 0 }}>
              Deterministic code computes; AI explains. There is no BUY button in this product, by
              design (§4, law 6).
            </p>
          </div>
        </nav>

        <main className="content" id="main" tabIndex={-1}>
          {renderScreen()}
        </main>
      </div>
    </>
  );
}

function RailItem({
  item,
  current,
  onGo,
}: {
  item: (typeof NAV_ITEMS)[number];
  current: ScreenId;
  onGo: (id: ScreenId) => void;
}) {
  const isCurrent = current === item.id;
  return (
    <button
      className="rail-item"
      aria-current={isCurrent ? "page" : undefined}
      title={item.blurb}
      onClick={() => onGo(item.id)}
    >
      <span>{item.label}</span>
      {item.awaitingPhase && <span className="rail-phase">{item.awaitingPhase}</span>}
    </button>
  );
}
