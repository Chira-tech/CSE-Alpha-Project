import { Suspense, lazy, useEffect, useState } from "react";
import { AUTH_REQUIRED_EVENT, getAuthStatus, logout } from "./api";
import { LoginScreen } from "./components/LoginScreen";
import { RunCapture } from "./components/RunCapture";
import { useReviewerName } from "./hooks/useReviewerName";
import { NAV_ITEMS, REVIEW_SCREEN, type ScreenId } from "./nav";
import { CompaniesScreen } from "./screens/CompaniesScreen";
import { CompanyScreen } from "./screens/CompanyScreen";
import { DataHealthScreen } from "./screens/DataHealthScreen";
import { JournalScreen } from "./screens/JournalScreen";
import { MacroScreen } from "./screens/MacroScreen";
import { NotBuiltScreen } from "./screens/NotBuiltScreen";
import { OpportunitiesScreen } from "./screens/OpportunitiesScreen";
import { PortfolioScreen } from "./screens/PortfolioScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { TodayScreen } from "./screens/TodayScreen";

// M5 — Convergence Engine & Playbook System (docs/CLAUDE_CODE_BRIEF_M5.md
// §1.3's allowlisted frontend edit — see nav.ts's own comment for why
// this touches App.tsx too, one line beyond the brief's literal
// two-file list: `NAV_ITEMS` only decides what's IN THE RAIL; without a
// matching `case` here, clicking "Playbooks" would render `NotBuiltScreen`
// instead of the real (if still Task-1-minimal) lazy route below. Lazy
// so the M5 feature's own JS is never fetched at all unless this route
// is actually visited — with the flag off, nothing ever navigates here,
// so this import is simply never triggered.
const PlaybooksRoute = lazy(() => import("./features/playbooks"));

export function App() {
  const [screen, setScreen] = useState<ScreenId>("today");
  const [openTicker, setOpenTicker] = useState<string | null>(null);
  const { name, setName } = useReviewerName();

  // The hosted-deployment access gate (app.security) — `null` while the
  // one status check is in flight. Left `{required: false, ...}` on a
  // failed check (rather than getting stuck showing neither the app nor
  // a login form): a network error here means every other screen is
  // about to fail exactly the same way and show its own error state,
  // and a broken auth check must never be the thing that locks a
  // legitimate, already-logged-in user out.
  const [auth, setAuth] = useState<{ required: boolean; authenticated: boolean } | null>(null);

  useEffect(() => {
    getAuthStatus()
      .then(setAuth)
      .catch(() => setAuth({ required: false, authenticated: true }));
    function onAuthRequired() {
      setAuth({ required: true, authenticated: false });
    }
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
  }, []);

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
    // A ticker drilled into from ANY screen (Companies, Portfolio,
    // Opportunities) opens the same company file — `screen` itself never
    // changes, so "back" returns to whichever screen the click came from.
    if (openTicker) {
      const backLabel =
        screen === "portfolio"
          ? "Portfolio"
          : screen === "opportunities"
            ? "Opportunities"
            : screen === "macro"
              ? "Macro"
              : "All companies";
      return (
        <CompanyScreen
          ticker={openTicker}
          onBack={() => setOpenTicker(null)}
          onOpen={setOpenTicker}
          backLabel={backLabel}
        />
      );
    }
    switch (screen) {
      case "today":
        return <TodayScreen onOpenScreen={(id) => go(id)} onOpen={setOpenTicker} />;
      case "companies":
        return <CompaniesScreen onOpen={setOpenTicker} />;
      case "macro":
        return <MacroScreen onOpen={setOpenTicker} />;
      case "portfolio":
        return <PortfolioScreen onOpen={setOpenTicker} />;
      case "opportunities":
        return <OpportunitiesScreen onOpen={setOpenTicker} />;
      case "journal":
        return <JournalScreen />;
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
      case "playbooks":
        return (
          <Suspense fallback={<div className="route stack">Loading…</div>}>
            <PlaybooksRoute />
          </Suspense>
        );
      default: {
        const item = NAV_ITEMS.find((i) => i.id === screen);
        return item ? <NotBuiltScreen item={item} /> : null;
      }
    }
  }

  // Nothing renders until the one status check resolves, rather than a
  // flash of the real product before the gate can react — see the
  // `auth` state's own comment for why a failed check still resolves.
  if (!auth) return null;
  if (auth.required && !auth.authenticated) {
    return <LoginScreen onSuccess={() => setAuth({ required: true, authenticated: true })} />;
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
            <div className="t-caption">8 of 9 screens built · Lab still open</div>
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
            <RunCapture />
            {auth.required && (
              <button
                className="btn-link t-caption"
                onClick={() => {
                  logout().finally(() => setAuth({ required: true, authenticated: false }));
                }}
              >
                Log out
              </button>
            )}
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
