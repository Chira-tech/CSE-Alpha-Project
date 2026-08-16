/**
 * Mirrors the FastAPI response models exactly (backend/app/api/routes/
 * corporate_actions.py and fundamentals.py). Decimal fields come over the
 * wire as strings (pydantic v2's default JSON encoding for Decimal, which
 * preserves precision that a JS number would silently round) — never
 * parse them to `number` for display; only for arithmetic you actually
 * need, and even then prefer showing the server's own string back to the
 * user unless you have a specific reason to reformat it.
 */

export type CorporateActionType =
  | "dividend_cash"
  | "bonus_issue"
  | "rights_issue"
  | "stock_split"
  | "consolidation"
  | "delisting"
  | "suspension";

export interface CorporateAction {
  id: number;
  ticker: string;
  ex_date: string; // YYYY-MM-DD
  type: CorporateActionType;
  ratio: string | null;
  cash_amount: string | null;
  subscription_price: string | null;
  cum_rights_price: string | null;
  terp: string | null;
  source_url: string | null;
  notes: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  rejected_by: string | null;
  rejected_at: string | null;
}

export type ProvenanceTier = "R" | "D" | "N" | "E" | "F" | "A" | "-";

export interface Fundamental {
  id: number;
  ticker: string;
  period_end: string;
  period_type: string;
  first_available_date: string;
  version: number;
  statement_line: string;
  value: string;
  currency: string;
  provenance_tier: ProvenanceTier;
  restated_flag: boolean;
  source_url: string | null;
  source_page: number | null;
  source_snippet: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

export interface ApiError {
  detail: string;
}
