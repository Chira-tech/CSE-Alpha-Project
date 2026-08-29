import type {
  Spread,
  CompanyValuation,
  CompositeScore,
  ConfirmBatchResult,
  CorporateAction,
  DataHealth,
  Decision,
  DecisionAction,
  Fundamental,
  FundamentalsPage,
  IndexHistory,
  JobKey,
  JobRun,
  JobsStatus,
  MarketOverview,
  MonteCarlo,
  OpportunityRanking,
  PortfolioSnapshotDetail,
  PriceHistoryPage,
  ScenarioSet,
  SectorDrilldown,
  SectorSensitivity,
  SecurityDetail,
  SecurityListItem,
  Tornado,
  ValuedPortfolio,
  RegimeGauge,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiRequestError extends Error {
  constructor(
    message: string,
    public status: number,
    /** FastAPI's raw `detail` value, whatever shape it was. Almost always
     * a string (surfaced as `message` above too), but `POST /jobs/{job}/
     * run`'s 429 sends `{message, retry_after}` — callers that need
     * `retry_after` read it from here rather than parsing `message`. */
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    // FastAPI's HTTPException body is {"detail": ...} — surface that
    // directly rather than a generic "request failed", since the detail
    // is usually the exact reason a confirm/reject was refused (e.g.
    // "already confirmed", or which fields are missing).
    let message = response.statusText;
    let detail: unknown = undefined;
    try {
      const body = await response.json();
      detail = body?.detail;
      if (typeof detail === "string") message = detail;
    } catch {
      // response body wasn't JSON — fall back to statusText, already set
    }
    throw new ApiRequestError(message, response.status, detail);
  }
  return response.json() as Promise<T>;
}

// --- Market / companies / health -----------------------------------------

export function getMarketOverview() {
  return request<MarketOverview>("/market");
}

export function listSecurities(search?: string) {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  return request<SecurityListItem[]>(`/securities?${params}`);
}

export function getSecurity(ticker: string) {
  return request<SecurityDetail>(`/securities/${encodeURIComponent(ticker)}`);
}

/** Paged, most-recent-first — backs the company file's price-history
 * table. The backend does the paging with SQL limit/offset, so a page
 * request only ever loads `limit` rows, never the full history. */
export function getSecurityPrices(ticker: string, limit: number, offset: number) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request<PriceHistoryPage>(`/securities/${encodeURIComponent(ticker)}/prices?${params}`);
}

export function getDataHealth() {
  return request<DataHealth>("/data-health");
}

export function getValuation(ticker: string) {
  return request<CompanyValuation>(`/valuation/${encodeURIComponent(ticker)}`);
}

/** §23's Bear/Base/Bull set + sensitivity tornado — cheap enough to fetch
 * alongside the rest of the fair-value page (a handful of DCF re-runs,
 * not the 10,000-draw Monte Carlo below). */
export function getScenarios(ticker: string) {
  return request<ScenarioSet>(`/valuation/${encodeURIComponent(ticker)}/scenarios`);
}

export function getTornado(ticker: string) {
  return request<Tornado>(`/valuation/${encodeURIComponent(ticker)}/tornado`);
}

/** §23's 10,000-draw Monte Carlo overlay — deliberately NOT fetched
 * automatically alongside the rest of the fair-value page (10,000 real
 * DCF re-runs); callers fetch this lazily, on demand. */
export function getMonteCarlo(ticker: string) {
  return request<MonteCarlo>(`/valuation/${encodeURIComponent(ticker)}/monte-carlo`);
}

/** §38's composite score — a real, honestly PARTIAL number (see
 * `CompositeScore.is_partial`): 5 of 7 pillars are blended, Valuation
 * and Growth are always shown as evidence only, per-ticker gaps in the
 * rest are named on each pillar's own `reason`. */
export function getCompositeScore(ticker: string) {
  return request<CompositeScore>(`/composite-score/${encodeURIComponent(ticker)}`);
}

// --- Corporate actions --------------------------------------------------

export function listCorporateActions(opts: { pendingOnly?: boolean; ticker?: string } = {}) {
  const params = new URLSearchParams();
  if (opts.pendingOnly !== undefined) params.set("pending_only", String(opts.pendingOnly));
  if (opts.ticker) params.set("ticker", opts.ticker);
  return request<CorporateAction[]>(`/corporate-actions?${params}`);
}

export function patchCorporateActionDraft(
  id: number,
  patch: Partial<Pick<CorporateAction, "ratio" | "cash_amount" | "subscription_price" | "cum_rights_price" | "notes">>,
) {
  return request<CorporateAction>(`/corporate-actions/${id}/draft`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function confirmCorporateAction(id: number, actor: string) {
  return request<CorporateAction>(`/corporate-actions/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({ actor }),
  });
}

export function rejectCorporateAction(id: number, actor: string) {
  return request<CorporateAction>(`/corporate-actions/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ actor }),
  });
}

// --- Fundamentals ---------------------------------------------------------

/** Paged — the Fundamentals tab defaults to 20/page, Previous/Next, not
 * the whole queue loaded and sliced client-side (mirrors
 * `getSecurityPrices`'s own real reason for existing). */
export function listFundamentals(
  opts: { pendingOnly?: boolean; ticker?: string; limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams();
  if (opts.pendingOnly !== undefined) params.set("pending_only", String(opts.pendingOnly));
  if (opts.ticker) params.set("ticker", opts.ticker);
  params.set("limit", String(opts.limit ?? 20));
  params.set("offset", String(opts.offset ?? 0));
  return request<FundamentalsPage>(`/fundamentals?${params}`);
}

export function confirmFundamental(id: number, actor: string, correctedValue?: string) {
  return request<Fundamental>(`/fundamentals/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({
      actor,
      correction: correctedValue ? { value: correctedValue } : null,
    }),
  });
}

/** "Select all, confirm multiples" — never carries a per-row correction;
 * a reviewer who needs to fix a value first uses the single-row Confirm,
 * which still supports that. One bad id doesn't fail the rest of the
 * batch — see `ConfirmBatchResult`'s own fields. */
export function confirmFundamentalsBatch(ids: number[], actor: string) {
  return request<ConfirmBatchResult>("/fundamentals/confirm-batch", {
    method: "POST",
    body: JSON.stringify({ actor, ids }),
  });
}

/** R1 T2.5: the safe bulk path — only promotes rows the server itself
 * re-verifies as corroborated (an independently-sourced REPORTED row
 * with the exact same value). Anything else in `ids` comes back in
 * `failed`, never silently promoted. */
export function confirmFundamentalsBatchCorroborated(ids: number[], actor: string) {
  return request<ConfirmBatchResult>("/fundamentals/confirm-batch-corroborated", {
    method: "POST",
    body: JSON.stringify({ actor, ids }),
  });
}

export function getIndexHistory() {
  return request<IndexHistory>("/market/index-history");
}

export function getSpread() {
  return request<Spread>("/market/spread");
}

export function getSectorSensitivity() {
  return request<SectorSensitivity>("/market/sector-sensitivity");
}

/** §31's regime gauge. Genuinely slow the first time (a real Markov fit,
 * an ARDL bounds test and the whole §33 matrix), so callers should load
 * it alongside the rest of Macro rather than blocking on it. */
export function getRegimeGauge() {
  return request<RegimeGauge>("/market/regime");
}

/** R1 T4.6.4. A real ~18s cost the first time it's called (reuses the
 * whole-universe `opportunity_ranking_for` — see `app.domain.
 * sector_drilldown_view`'s own docstring), paid on the user's own click
 * into a sector, not on page load. */
export function getSectorDrilldown(sector: string) {
  return request<SectorDrilldown>(`/market/sector/${encodeURIComponent(sector)}`);
}

// --- Opportunities ------------------------------------------------------

export function getOpportunityRanking() {
  return request<OpportunityRanking>("/opportunities");
}

// --- Decisions (§45 journal) ---------------------------------------------

export function listDecisions() {
  return request<Decision[]>("/decisions");
}

export function createDecision(body: {
  ticker: string;
  action: DecisionAction;
  reasoning_text: string;
  size_pct?: string;
  limit_price?: string;
  conviction_1_5?: number;
  falsification_text?: string;
}) {
  return request<Decision>("/decisions", { method: "POST", body: JSON.stringify(body) });
}

export function recordOutcome(
  decisionId: number,
  body: { exit_date: string; exit_price: string; exit_trigger: string },
) {
  return request<Decision>(`/decisions/${decisionId}/outcomes`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- Portfolio --------------------------------------------------------

export function getPortfolioHoldingsValued() {
  return request<ValuedPortfolio | null>("/portfolio/holdings/valued");
}

/**
 * Multipart upload, deliberately not routed through `request()` above:
 * that helper always sets `Content-Type: application/json`, which would
 * corrupt a multipart body — the browser must set its own
 * `Content-Type` (with the multipart boundary) when the body is a
 * `FormData`, so no Content-Type header is set here at all.
 */
// --- Jobs (P1.1 "Run Capture") --------------------------------------------

export function getJobsStatus() {
  return request<JobsStatus>("/jobs/status");
}

/**
 * `enqueue`-only — see `app.jobs.runner`'s own docstring. Returns
 * immediately with a `queued` row; the always-on worker (not this
 * request) is what actually runs the job. Throws `ApiRequestError` with
 * status 409 (already running) or 429 (15-minute manual cooldown — the
 * message carries `{message, retry_after}` as a JSON string, since
 * FastAPI's own `HTTPException.detail` here is an object, not a plain
 * string).
 */
export function runJob(job: JobKey) {
  return request<JobRun>(`/jobs/${encodeURIComponent(job)}/run`, { method: "POST" });
}

export function cancelJob(runId: number) {
  return request<JobRun>(`/jobs/${runId}/cancel`, { method: "POST" });
}

/**
 * Not routed through `request()`: this is a URL for `EventSource`, which
 * makes its own GET request outside `fetch` and can't carry a JSON
 * `Content-Type` header (nor would one mean anything for an SSE GET).
 */
export function jobStreamUrl(runId: number): string {
  return `${BASE_URL}/jobs/${runId}/stream`;
}

/** R1 T3.1/T3.2: both export endpoints are real files, not JSON, so
 * neither goes through `request()` above — same reason `uploadPortfolio`
 * below doesn't. Filename comes from the server's own `Content-
 * Disposition` header when present (it always is here) so the saved
 * file's date matches when the export actually ran, not the click. */
async function downloadFile(path: string, fallbackFilename: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // response body wasn't JSON — fall back to statusText
    }
    throw new ApiRequestError(detail, response.status);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return { blob: await response.blob(), filename: match ? match[1] : fallbackFilename };
}

export function downloadWorkbook() {
  return downloadFile("/export/workbook", "cse-alpha-workbook.xlsx");
}

export function downloadBackup() {
  return downloadFile("/export/backup", "cse-alpha-backup.zip");
}

export async function uploadPortfolio(file: File): Promise<PortfolioSnapshotDetail> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${BASE_URL}/portfolio/upload`, { method: "POST", body: form });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // response body wasn't JSON — fall back to statusText
    }
    throw new ApiRequestError(detail, response.status);
  }
  return response.json() as Promise<PortfolioSnapshotDetail>;
}
