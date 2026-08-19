import type {
  Spread,
  CompanyValuation,
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
  OpportunityRanking,
  PortfolioSnapshotDetail,
  PriceHistoryPage,
  SectorSensitivity,
  SecurityDetail,
  SecurityListItem,
  ValuedPortfolio,
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

export function getIndexHistory() {
  return request<IndexHistory>("/market/index-history");
}

export function getSpread() {
  return request<Spread>("/market/spread");
}

export function getSectorSensitivity() {
  return request<SectorSensitivity>("/market/sector-sensitivity");
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
