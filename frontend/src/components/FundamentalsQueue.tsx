import { useEffect, useState } from "react";
import {
  ApiRequestError,
  confirmFundamental,
  confirmFundamentalsBatch,
  confirmFundamentalsBatchCorroborated,
  listFundamentals,
} from "../api";
import { downloadCsv, toCsv } from "../csv";
import type { ConfirmBatchFailure, Fundamental, FundamentalsPage } from "../types";
import { ProvenanceChip } from "./ProvenanceChip";
import { EmptyState, ErrorState, SkeletonTable } from "./states";

const PAGE_SIZE = 20;

/** The server caps a single page at 200 (`GET /fundamentals`'s own
 * `le=200`), so exporting the whole queue means paging through it —
 * the same discipline the earlier bulk-confirm pass used, just reading
 * instead of writing. */
const EXPORT_PAGE_SIZE = 200;

const EXPORT_COLUMNS: { key: keyof Fundamental; header: string }[] = [
  { key: "id", header: "id" },
  { key: "ticker", header: "ticker" },
  { key: "period_end", header: "period_end" },
  { key: "period_type", header: "period_type" },
  { key: "statement_line", header: "statement_line" },
  { key: "value", header: "value" },
  { key: "currency", header: "currency" },
  { key: "provenance_tier", header: "provenance_tier" },
  { key: "restated_flag", header: "restated_flag" },
  { key: "source_url", header: "source_url" },
  { key: "source_page", header: "source_page" },
  { key: "source_snippet", header: "source_snippet" },
  { key: "confirmed_by", header: "confirmed_by" },
  { key: "confirmed_at", header: "confirmed_at" },
];

async function fetchAllPending(): Promise<Fundamental[]> {
  const all: Fundamental[] = [];
  let offset = 0;
  for (;;) {
    const page = await listFundamentals({ pendingOnly: true, limit: EXPORT_PAGE_SIZE, offset });
    all.push(...page.items);
    offset += page.items.length;
    if (page.items.length === 0 || offset >= page.total) break;
  }
  return all;
}

interface RowProps {
  row: Fundamental;
  reviewerName: string;
  selected: boolean;
  onToggleSelected: (id: number) => void;
  onChanged: (updated: Fundamental) => void;
  onRemoved: (id: number) => void;
}

function Row({ row, reviewerName, selected, onToggleSelected, onChanged, onRemoved }: RowProps) {
  const [value, setValue] = useState(row.value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);
  const corrected = value !== row.value;

  async function confirm() {
    if (!reviewerName.trim()) {
      setError("Enter your name above before confirming.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await confirmFundamental(row.id, reviewerName.trim(), corrected ? value : undefined);
      onChanged(updated);
      onRemoved(row.id);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <tr>
        <td>
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelected(row.id)}
            aria-label={`Select ${row.ticker} ${row.statement_line} for bulk confirm`}
          />
        </td>
        <th
          scope="row"
          className="mono"
          style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}
        >
          {row.ticker}
        </th>
        <td className="num">{row.period_end}</td>
        <td>{row.period_type}</td>
        <td className="mono">{row.statement_line}</td>
        <td>
          <label className="t-label" htmlFor={`f-${row.id}`} style={{ display: "block" }}>
            Value
          </label>
          <input
            id={`f-${row.id}`}
            className="num input-narrow"
            type="text"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          {corrected && (
            <>
              {" "}
              <span className="status-tag status-pending">corrected</span>
            </>
          )}
        </td>
        <td>
          <ProvenanceChip tier={row.provenance_tier} />
          {row.corroborated && (
            <>
              {" "}
              <span
                className="chip"
                title="An independently-sourced filing already reports this exact same figure — safe for one-click bulk confirm (R1 T2.5)."
                style={{ borderColor: "var(--border-strong)", color: "var(--ink-3)" }}
              >
                corroborated
              </span>
            </>
          )}
        </td>
        <td>
          {row.source_snippet && (
            <button className="btn-link" onClick={() => setShowSource((s) => !s)} aria-expanded={showSource}>
              {showSource ? "hide source" : "show source"}
            </button>
          )}
        </td>
        <td>
          <div className="stack-tight">
            <button className="btn-primary" onClick={confirm} disabled={busy}>
              Confirm
            </button>
            {error && (
              <p className="t-caption" role="alert" style={{ color: "var(--neg-strong)", margin: 0 }}>
                {error}
              </p>
            )}
          </div>
        </td>
      </tr>
      {showSource && (
        <tr>
          <td colSpan={9}>
            {/* §8: an AI-assisted figure "must show the source snippet". */}
            <pre className="code-block">{row.source_snippet}</pre>
            {row.source_url && (
              <a className="t-caption" href={row.source_url} target="_blank" rel="noreferrer">
                open the filed PDF
                {row.source_page !== null ? ` (page ${row.source_page + 1})` : ""}
              </a>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export function FundamentalsQueue({ reviewerName }: { reviewerName: string }) {
  const [page, setPage] = useState<FundamentalsPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchNotice, setBatchNotice] = useState<{ confirmedCount: number; failed: ConfirmBatchFailure[] } | null>(
    null,
  );
  const [batchError, setBatchError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    setPage(null);
    setError(null);
    setSelected(new Set());
    setBatchNotice(null);
    setBatchError(null);
    listFundamentals({ pendingOnly: true, limit: PAGE_SIZE, offset })
      .then(setPage)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }, [offset]);

  function updateRow(updated: Fundamental) {
    setPage((p) => (p ? { ...p, items: p.items.map((x) => (x.id === updated.id ? updated : x)) } : p));
  }

  function removeRows(ids: number[]) {
    const idSet = new Set(ids);
    setPage((p) =>
      p
        ? { ...p, items: p.items.filter((x) => !idSet.has(x.id)), total: Math.max(0, p.total - ids.length) }
        : p,
    );
    setSelected((s) => {
      const next = new Set(s);
      ids.forEach((id) => next.delete(id));
      return next;
    });
  }

  function toggleSelected(id: number) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (!page) return;
    setSelected((s) => (s.size === page.items.length ? new Set() : new Set(page.items.map((r) => r.id))));
  }

  async function confirmSelected() {
    if (!reviewerName.trim()) {
      setBatchError("Enter your name above before confirming.");
      return;
    }
    setBatchBusy(true);
    setBatchError(null);
    setBatchNotice(null);
    try {
      const result = await confirmFundamentalsBatch(Array.from(selected), reviewerName.trim());
      removeRows(result.confirmed);
      setBatchNotice({ confirmedCount: result.confirmed.length, failed: result.failed });
    } catch (e) {
      setBatchError(e instanceof ApiRequestError ? e.message : "Request failed");
    } finally {
      setBatchBusy(false);
    }
  }

  /** R1 T2.5: confirms every row on this page the SERVER has independently
   * verified as corroborated — never a selection-driven action, so there's
   * no way to accidentally include an uncorroborated row by having it
   * checked at the time. */
  const corroboratedIds = page ? page.items.filter((r) => r.corroborated).map((r) => r.id) : [];

  async function confirmCorroborated() {
    if (!reviewerName.trim()) {
      setBatchError("Enter your name above before confirming.");
      return;
    }
    setBatchBusy(true);
    setBatchError(null);
    setBatchNotice(null);
    try {
      const result = await confirmFundamentalsBatchCorroborated(corroboratedIds, reviewerName.trim());
      removeRows(result.confirmed);
      setBatchNotice({ confirmedCount: result.confirmed.length, failed: result.failed });
    } catch (e) {
      setBatchError(e instanceof ApiRequestError ? e.message : "Request failed");
    } finally {
      setBatchBusy(false);
    }
  }

  /** Exports the ENTIRE pending queue, not just the current 20-row page —
   * a same-page-only export would defeat the point of checking the queue
   * by hand outside the app. */
  async function exportToCsv() {
    setExporting(true);
    setExportError(null);
    try {
      const rows = await fetchAllPending();
      const csv = toCsv(rows, EXPORT_COLUMNS);
      const today = new Date().toISOString().slice(0, 10);
      downloadCsv(`fundamentals-queue-${today}.csv`, csv);
    } catch (e) {
      setExportError(e instanceof ApiRequestError ? e.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  function goToPreviousPage() {
    setOffset((o) => Math.max(0, o - PAGE_SIZE));
  }

  function goToNextPage() {
    setOffset((o) => (page && o + page.items.length < page.total ? o + PAGE_SIZE : o));
  }

  if (error) {
    return (
      <ErrorState
        whatFailed="The fundamentals queue could not be loaded"
        whatItAffects="This queue only."
        whatStillWorks="The corporate-actions queue and every other screen."
        whatHappensNext={<>Check the API is reachable, then reload. Underlying error: {error}</>}
      />
    );
  }
  if (!page) return <SkeletonTable rows={4} columns={9} />;
  if (page.total === 0) {
    return (
      <EmptyState title="Nothing pending.">
        <p style={{ margin: 0 }}>
          Every AI-assisted extraction has been reviewed. New figures appear here when the
          financial-statement scan reads a newly filed PDF.
        </p>
      </EmptyState>
    );
  }

  const allOnPageSelected = page.items.length > 0 && selected.size === page.items.length;

  return (
    <div className="stack-tight">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="row" style={{ alignItems: "center", gap: "var(--s3)" }}>
          <button className="btn-primary" onClick={confirmSelected} disabled={selected.size === 0 || batchBusy}>
            Confirm {selected.size > 0 ? `${selected.size} selected` : "selected"}
          </button>
          {corroboratedIds.length > 0 && (
            <button
              onClick={confirmCorroborated}
              disabled={batchBusy}
              title="Each of these has an independently-sourced filing already reporting the exact same figure — the one case safe for one-click confirm (R1 T2.5)."
            >
              Confirm {corroboratedIds.length} corroborated
            </button>
          )}
          <button onClick={exportToCsv} disabled={exporting}>
            {exporting ? "Exporting…" : `Export ${page.total.toLocaleString("en-LK")} to CSV`}
          </button>
          {exportError && (
            <p className="t-caption" role="alert" style={{ margin: 0, color: "var(--neg-strong)" }}>
              {exportError}
            </p>
          )}
          {batchError && (
            <p className="t-caption" role="alert" style={{ margin: 0, color: "var(--neg-strong)" }}>
              {batchError}
            </p>
          )}
          {batchNotice && (
            <p className="t-caption" role="status" style={{ margin: 0 }}>
              {batchNotice.confirmedCount > 0 && (
                <span style={{ color: "var(--pos-strong)" }}>{batchNotice.confirmedCount} confirmed. </span>
              )}
              {batchNotice.failed.length > 0 && (
                <span style={{ color: "var(--neg-strong)" }}>
                  {batchNotice.failed.length} could not be confirmed:{" "}
                  {batchNotice.failed.map((f) => `#${f.id} (${f.reason})`).join("; ")}
                </span>
              )}
            </p>
          )}
        </div>
        <span className="t-caption num">
          {page.total === 0 ? "0 of 0" : `${page.offset + 1}–${page.offset + page.items.length} of ${page.total}`}
        </span>
      </div>

      <div className="table-wrap table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">
                <input
                  type="checkbox"
                  checked={allOnPageSelected}
                  onChange={toggleSelectAll}
                  aria-label="Select all rows on this page"
                />
              </th>
              <th scope="col">Ticker</th>
              <th scope="col">Period end</th>
              <th scope="col">Type</th>
              <th scope="col">Line</th>
              <th scope="col">Value</th>
              <th scope="col">Provenance</th>
              <th scope="col">Source</th>
              <th scope="col">Review</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((r) => (
              <Row
                key={r.id}
                row={r}
                reviewerName={reviewerName}
                selected={selected.has(r.id)}
                onToggleSelected={toggleSelected}
                onChanged={updateRow}
                onRemoved={(id) => removeRows([id])}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="row" style={{ justifyContent: "flex-end", alignItems: "center", gap: "var(--s3)" }}>
        <span className="t-caption num">
          {page.total === 0 ? "0 of 0" : `${page.offset + 1}–${page.offset + page.items.length} of ${page.total}`}
        </span>
        <button onClick={goToPreviousPage} disabled={page.offset === 0}>
          ← Previous
        </button>
        <button onClick={goToNextPage} disabled={page.offset + page.items.length >= page.total}>
          Next →
        </button>
      </div>
    </div>
  );
}
