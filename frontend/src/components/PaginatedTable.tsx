import { useEffect, useState } from "react";

/**
 * R1 brief §5.0 — every long table gets: a page-size selector, previous/
 * next, and a "showing X-Y of Z" readout. This is the CLIENT-SIDE form
 * (the caller already has the full, real row array — e.g. Opportunities'
 * ranked list, or one company's own financial-statement lines — and this
 * component only slices it for display) — distinct from `Fundamentals
 * Queue.tsx`'s own SERVER-side paging, which stays as its own bespoke
 * implementation because the real confirm queue can hold 35,000+ rows
 * and must never fetch the whole thing at once.
 *
 * SCOPE DECISION, disclosed rather than silently skipped: the brief also
 * asks for sort/page state "in the URL so views are shareable and
 * survive refresh." This app has no router (`App.tsx`'s own screen
 * switch is local component state, not URL-addressed) — wiring real
 * per-table URL state would mean introducing routing as a prerequisite,
 * a materially bigger change than this component itself. Page/sort
 * state here is real and controlled, just not yet URL-persisted.
 */
export function usePagination<T>(rows: T[], defaultPageSize: number) {
  const [pageSize, setPageSize] = useState(defaultPageSize);
  const [offset, setOffset] = useState(0);

  // A new, shorter row array (e.g. after a filter changes) must not
  // leave the view stranded past the end of the new list.
  useEffect(() => {
    if (offset >= rows.length && rows.length > 0) setOffset(0);
  }, [rows.length, offset]);

  const page = rows.slice(offset, offset + pageSize);
  return {
    page,
    pageSize,
    offset,
    total: rows.length,
    setPageSize: (size: number) => {
      setPageSize(size);
      setOffset(0);
    },
    goToPrevious: () => setOffset((o) => Math.max(0, o - pageSize)),
    goToNext: () => setOffset((o) => (o + pageSize < rows.length ? o + pageSize : o)),
  };
}

export function PaginationControls({
  total,
  offset,
  pageSize,
  pageSizeOptions,
  shownCount,
  onPageSizeChange,
  onPrevious,
  onNext,
}: {
  total: number;
  offset: number;
  pageSize: number;
  pageSizeOptions: readonly number[];
  shownCount: number;
  onPageSizeChange: (size: number) => void;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (total === 0) return null;
  return (
    <div className="row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "var(--s3)" }}>
      <label className="t-caption" style={{ display: "flex", alignItems: "center", gap: "var(--s2)" }}>
        Show
        <select value={pageSize} onChange={(e) => onPageSizeChange(Number(e.target.value))}>
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        per page
      </label>
      <span className="t-caption num">
        {offset + 1}–{offset + shownCount} of {total.toLocaleString("en-LK")}
      </span>
      <div className="row" style={{ gap: "var(--s2)" }}>
        <button onClick={onPrevious} disabled={offset === 0}>
          ← Previous
        </button>
        <button onClick={onNext} disabled={offset + shownCount >= total}>
          Next →
        </button>
      </div>
    </div>
  );
}
