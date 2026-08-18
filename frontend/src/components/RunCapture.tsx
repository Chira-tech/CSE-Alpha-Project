import { useEffect, useRef, useState } from "react";
import { ApiRequestError, cancelJob, getJobsStatus, jobStreamUrl, runJob } from "../api";
import { notifyDataRefreshed } from "../dataRefresh";
import { formatAgo } from "../format";
import type { JobKey, JobRun, JobStatusEntry, JobsStatus } from "../types";

/**
 * P1.1 (`docs/CLAUDE_CODE_BRIEF.md`, TASK 1.1) — the sidebar's manual
 * "Run Capture" control, rendered once in `App.tsx`'s `rail-foot` so it
 * (and any run it's watching) survives screen navigation.
 *
 * Only jobs with a real, disclosed expected cadence — a cron entry in
 * `app.jobs.scheduler` — get a freshness dot below; `enrich_securities`
 * and `recompute` are real, triggerable jobs (still offered in the menu)
 * but have no schedule of their own to be "stale" against, so showing a
 * dot for them would invent an expectation this system doesn't actually
 * have.
 */
const FRESHNESS_JOBS: JobKey[] = [
  "capture_prices",
  "capture_market",
  "capture_macro",
  "capture_filings",
  "capture_corporate_actions",
];

const STATUS_POLL_MS = 60_000;

export function RunCapture() {
  const [status, setStatus] = useState<JobsStatus | null>(null);
  const [activeRun, setActiveRun] = useState<JobRun | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const activeRunRef = useRef<JobRun | null>(null);
  activeRunRef.current = activeRun;

  function startWatching(run: JobRun) {
    setActiveRun(run);
    eventSourceRef.current?.close();
    const es = new EventSource(jobStreamUrl(run.id));
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      const payload = JSON.parse(event.data) as JobRun;
      setActiveRun(payload);
      if (payload.status !== "queued" && payload.status !== "running") {
        es.close();
        eventSourceRef.current = null;
        setActiveRun(null);
        refreshStatus();
        // §1.1: "invalidate the query cache ... do not force a page
        // reload." Only on a genuine success — a failed or cancelled
        // run shouldn't tell other screens their data just got fresher.
        if (payload.status === "success") notifyDataRefreshed();
      }
    };
    es.onerror = () => {
      // The stream closes itself server-side once the run reaches a
      // terminal status; a real connection drop just stops updates
      // here rather than throwing — the next status poll still reports
      // the real outcome.
      es.close();
      eventSourceRef.current = null;
    };
  }

  function refreshStatus() {
    getJobsStatus()
      .then((s) => {
        setStatus(s);
        // Resume watching a run already in progress — e.g. this
        // component just remounted while a manual sweep from before was
        // still going.
        if (activeRunRef.current) return;
        const inFlight = s.jobs
          .map((j) => j.last_run)
          .find((r): r is JobRun => r !== null && (r.status === "queued" || r.status === "running"));
        if (inFlight) startWatching(inFlight);
      })
      .catch(() => {
        // Freshness dots are informational; a failed status fetch
        // degrades to "no dots shown" rather than an error banner
        // wedged into the sidebar's own foot.
      });
  }

  useEffect(() => {
    refreshStatus();
    const interval = window.setInterval(() => {
      if (!activeRunRef.current) refreshStatus();
    }, STATUS_POLL_MS);
    return () => {
      window.clearInterval(interval);
      eventSourceRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    function onDocClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  async function handleRun(job: JobKey) {
    setMenuOpen(false);
    setNotice(null);
    try {
      const run = await runJob(job);
      startWatching(run);
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 409) {
        setNotice(`${job} is already running.`);
      } else if (err instanceof ApiRequestError && err.status === 429) {
        const detail = err.detail as { retry_after?: number } | undefined;
        const mins = detail?.retry_after ? Math.ceil(detail.retry_after / 60) : null;
        setNotice(
          mins
            ? `Try again in ${mins}m — manual runs are limited to once every 15 minutes per job.`
            : err.message,
        );
      } else {
        setNotice(err instanceof ApiRequestError ? err.message : "Could not start the job.");
      }
      window.setTimeout(() => setNotice(null), 8000);
    }
  }

  async function handleCancel() {
    if (!activeRun) return;
    try {
      await cancelJob(activeRun.id);
    } catch {
      // Best-effort — the SSE stream still shows the real outcome
      // regardless of whether this particular request succeeded.
    }
  }

  const freshness = FRESHNESS_JOBS.map((key) => status?.jobs.find((j) => j.job === key)).filter(
    (j): j is JobStatusEntry => j != null,
  );
  const fullCapture = status?.jobs.find((j) => j.job === "capture_all");
  const menuJobs = status?.jobs.filter((j) => j.job !== "capture_all") ?? [];

  return (
    <div className="run-capture" ref={containerRef}>
      <div className="t-label run-capture-heading">Data</div>
      <ul className="freshness-list">
        {freshness.map((entry) => (
          <FreshnessRow key={entry.job} entry={entry} />
        ))}
      </ul>

      {activeRun ? (
        <div className="run-capture-progress" role="status" aria-live="polite">
          <div className="meter run-capture-meter">
            <span
              className="meter-fill"
              style={{ width: `${Math.min(100, Math.max(0, Number(activeRun.progress_pct) || 0))}%` }}
            />
          </div>
          <div className="t-caption run-capture-note">
            {activeRun.progress_note ?? `${activeRun.label}…`}
          </div>
          <button className="btn-link" onClick={handleCancel}>
            Cancel
          </button>
        </div>
      ) : (
        <>
          <button
            className="btn-primary run-capture-trigger"
            onClick={() => setMenuOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            Run Capture ▸
          </button>
          {menuOpen && (
            <div className="run-capture-menu" role="menu">
              {menuJobs.map((j) => (
                <button key={j.job} role="menuitem" onClick={() => handleRun(j.job)}>
                  {j.label}
                </button>
              ))}
              <div className="run-capture-menu-divider" role="separator" />
              <button role="menuitem" onClick={() => handleRun("capture_all")}>
                Run everything
              </button>
            </div>
          )}
        </>
      )}

      {notice && (
        <p className="t-caption run-capture-notice" role="alert">
          {notice}
        </p>
      )}

      <p className="t-caption run-capture-last">
        Last full run:{" "}
        {fullCapture?.last_run
          ? formatAgo(fullCapture.last_run.finished_at ?? fullCapture.last_run.created_at)
          : "never"}
      </p>
    </div>
  );
}

function FreshnessRow({ entry }: { entry: JobStatusEntry }) {
  const lastSuccess = entry.last_run?.status === "success" ? entry.last_run : null;
  const finishedAt = lastSuccess?.finished_at ?? null;
  let dotState: "pos" | "caution" = "caution";
  if (finishedAt) {
    // The same >2-day threshold `DataHealthScreen` already treats as
    // stale for price data (§8/§50) — reused rather than a second,
    // independently-tuned number. It tolerates one ordinary weekend gap
    // the same way that screen's own threshold does.
    const ageDays = Math.floor((Date.now() - new Date(finishedAt).getTime()) / 86_400_000);
    dotState = ageDays > 2 ? "caution" : "pos";
  }
  return (
    <li className="freshness-row" title={entry.label}>
      <span className={`freshness-dot freshness-dot-${dotState}`} aria-hidden="true">
        {dotState === "pos" ? "●" : "▲"}
      </span>
      <span className="freshness-label">{entry.label}</span>
      <span className="t-caption freshness-age">
        {finishedAt ? formatAgo(finishedAt) : entry.last_run ? "never succeeded" : "never run"}
      </span>
    </li>
  );
}
