// M5 — Convergence Engine & Playbook System (docs/CLAUDE_CODE_BRIEF_M5.md).
// Task 1 (isolation scaffold) only: a lazy-loaded route, wrapped in its
// own error boundary so an unreachable /api/v5 (or any other failure in
// this feature) shows a fallback here and affects nothing else in the
// app (brief §8's own requirement, built now because it's part of the
// allowed wiring, not a Task 8 UI deliverable). Real tabs (Live,
// BaseRates, Studio, TrackRecord) are Task 8; this is intentionally just
// enough to prove the whole path — nav entry -> lazy route -> error
// boundary -> real backend call -> real response — actually works.
import { Component, useEffect, useState, type ReactNode } from "react";
import { getM5Status } from "./api";
import type { M5Status } from "./types";

class PlaybooksErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="route stack">
          <header className="screen-head">
            <h1>Playbooks</h1>
          </header>
          <div className="notice notice-neutral">
            <h3>This tab couldn't load</h3>
            <p className="prose t-body">
              Nothing else in the app is affected — {this.state.error.message}
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function PlaybooksBody() {
  const [status, setStatus] = useState<M5Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getM5Status()
      .then(setStatus)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="route stack">
      <header className="screen-head">
        <h1>Playbooks</h1>
        <p className="prose">Convergence setups, base rates, and the trial record</p>
      </header>

      <div className="notice notice-neutral">
        <h3>Not built yet — M5 Task 1 (isolation scaffold) only</h3>
        <p className="prose t-body">
          The state grid, base-rate cards, playbook studio and track record (Task 8) don't exist
          yet — this route exists to prove the isolation scaffold itself works end to end: this
          real component, calling the real <code>/api/v5/status</code> endpoint, on a backend that
          never touches an existing table.
        </p>
        {error && (
          <p className="prose t-body" role="alert">
            Could not reach <code>/api/v5/status</code>: {error}
          </p>
        )}
        {status && (
          <p className="prose t-body">
            Connected — M5 backend reports <code>m5_enabled={String(status.m5_enabled)}</code>,
            database <code>{status.database_url}</code>.
          </p>
        )}
      </div>
    </div>
  );
}

export default function Playbooks() {
  return (
    <PlaybooksErrorBoundary>
      <PlaybooksBody />
    </PlaybooksErrorBoundary>
  );
}
