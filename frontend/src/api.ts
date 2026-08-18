import type {
  Spread,
  CompanyValuation,
  CorporateAction,
  DataHealth,
  Fundamental,
  IndexHistory,
  MarketOverview,
  PortfolioSnapshotDetail,
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
    // FastAPI's HTTPException body is {"detail": "..."} — surface that
    // message directly rather than a generic "request failed", since the
    // detail is usually the exact reason a confirm/reject was refused
    // (e.g. "already confirmed", or which fields are missing).
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // response body wasn't JSON — fall back to statusText, already set
    }
    throw new ApiRequestError(detail, response.status);
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

export function listFundamentals(opts: { pendingOnly?: boolean; ticker?: string } = {}) {
  const params = new URLSearchParams();
  if (opts.pendingOnly !== undefined) params.set("pending_only", String(opts.pendingOnly));
  if (opts.ticker) params.set("ticker", opts.ticker);
  return request<Fundamental[]>(`/fundamentals?${params}`);
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

export function getIndexHistory() {
  return request<IndexHistory>("/market/index-history");
}

export function getSpread() {
  return request<Spread>("/market/spread");
}

export function getSectorSensitivity() {
  return request<SectorSensitivity>("/market/sector-sensitivity");
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
