import { useMemo, useState } from "react";
import { ApiRequestError, confirmFundamental } from "../api";
import { formatPrice } from "../format";
import type { FundamentalSummary } from "../types";
import { PaginationControls, usePagination } from "./PaginatedTable";
import { ProvenanceDot } from "./ProvenanceDot";
import { EmptyState } from "./states";

const PAGE_SIZE_OPTIONS = [10, 20, 30] as const;
const DEFAULT_PAGE_SIZE = 10;

/**
 * R1 T4.3.6 — "Convert to PaginatedTable. Default page size 10.
 * Selector 10/20/30. Default sort: awaiting confirmation first... Each
 * line shows ProvenanceDot. Inline confirm action on the row."
 *
 * The company file's own reviewer-name field, separate from the main
 * Data health -> Confirm queue's own — this table exists so a reviewer
 * already looking at one company's filings can clear a line without
 * navigating away, not to replace the queue's bulk tooling.
 */
export function FundamentalsLinesTable({ ticker, fundamentals, onConfirmed }: {
  ticker: string;
  fundamentals: FundamentalSummary[];
  onConfirmed: (updated: FundamentalSummary) => void;
}) {
  const [reviewerName, setReviewerName] = useState("");

  // Awaiting-confirmation-first, stable otherwise (the backend already
  // orders by period_end desc, statement_line — preserved as the
  // secondary key via a stable sort).
  const sorted = useMemo(() => {
    const awaiting = (f: FundamentalSummary) => (!f.confirmed && f.provenance_tier === "A" ? 0 : 1);
    return [...fundamentals].sort((a, b) => awaiting(a) - awaiting(b));
  }, [fundamentals]);

  const { page, pageSize, offset, total, setPageSize, goToPrevious, goToNext } = usePagination(
    sorted,
    DEFAULT_PAGE_SIZE,
  );

  if (fundamentals.length === 0) {
    return (
      <EmptyState title="No statement lines extracted.">
        <p style={{ margin: 0 }}>
          The financial-statement scan reads filed PDFs into this table. Extracted figures are
          marked AI-assisted and cannot enter any valuation until confirmed (§8).
        </p>
      </EmptyState>
    );
  }

  const awaitingCount = fundamentals.filter((f) => !f.confirmed && f.provenance_tier === "A").length;

  return (
    <div className="stack-tight">
      {awaitingCount > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: "var(--s3)", flexWrap: "wrap" }}>
          <label className="t-caption" htmlFor={`${ticker}-reviewer-name`}>
            Your name, to confirm a line below
          </label>
          <input
            id={`${ticker}-reviewer-name`}
            type="text"
            value={reviewerName}
            onChange={(e) => setReviewerName(e.target.value)}
            placeholder="Reviewer name"
            style={{ maxWidth: 220 }}
          />
        </div>
      )}
      <div className="table-wrap table-scroll">
        <table className="data-table">
          <caption className="t-caption" style={{ captionSide: "bottom", padding: "var(--s3)" }}>
            {awaitingCount} of {fundamentals.length} line{fundamentals.length === 1 ? "" : "s"} awaiting
            confirmation — sorted to the top.
          </caption>
          <thead>
            <tr>
              <th scope="col">Period end</th>
              <th scope="col">Type</th>
              <th scope="col">Line</th>
              <th scope="col" className="right">Value (LKR '000)</th>
              <th scope="col">Provenance</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>
            {page.map((f) => (
              <FundamentalRow key={f.id} f={f} reviewerName={reviewerName} onConfirmed={onConfirmed} />
            ))}
          </tbody>
        </table>
      </div>
      <PaginationControls
        total={total}
        offset={offset}
        pageSize={pageSize}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        shownCount={page.length}
        onPageSizeChange={setPageSize}
        onPrevious={goToPrevious}
        onNext={goToNext}
      />
    </div>
  );
}

function FundamentalRow({ f, reviewerName, onConfirmed }: {
  f: FundamentalSummary;
  reviewerName: string;
  onConfirmed: (updated: FundamentalSummary) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsConfirm = !f.confirmed && f.provenance_tier === "A";

  async function confirm() {
    if (!reviewerName.trim()) {
      setError("Enter your name above first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await confirmFundamental(f.id, reviewerName.trim());
      onConfirmed({
        id: f.id,
        period_end: f.period_end,
        period_type: f.period_type,
        statement_line: f.statement_line,
        value: updated.value,
        provenance_tier: updated.provenance_tier,
        confirmed: updated.confirmed_by !== null,
      });
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr>
      <th scope="row" className="num" style={rowHeadStyle}>{f.period_end}</th>
      <td>{f.period_type}</td>
      <td className="mono">{f.statement_line}</td>
      <td className="right num">{formatPrice(f.value)}</td>
      <td>
        <ProvenanceDot tier={f.provenance_tier} />
        {needsConfirm && (
          <>
            {" "}
            <span className="status-tag status-pending">awaiting review</span>
          </>
        )}
      </td>
      <td>
        {needsConfirm ? (
          <>
            <button className="btn-secondary" disabled={busy} onClick={confirm}>
              {busy ? "Confirming…" : "Confirm"}
            </button>
            {error && (
              <div className="t-caption" style={{ color: "var(--neg)", marginTop: "var(--s1)" }}>
                {error}
              </div>
            )}
          </>
        ) : (
          <span className="t-caption muted">—</span>
        )}
      </td>
    </tr>
  );
}

const rowHeadStyle = {
  background: "none",
  textTransform: "none" as const,
  letterSpacing: 0,
  fontSize: 13,
  fontWeight: 500,
  color: "var(--ink-1)",
};
