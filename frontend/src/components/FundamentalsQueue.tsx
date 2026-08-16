import { useEffect, useState } from "react";
import { ApiRequestError, confirmFundamental, listFundamentals } from "../api";
import type { Fundamental } from "../types";
import { ProvenanceChip } from "./ProvenanceChip";
import { EmptyState, ErrorState, SkeletonTable } from "./states";

interface RowProps {
  row: Fundamental;
  reviewerName: string;
  onChanged: (updated: Fundamental) => void;
  onRemoved: (id: number) => void;
}

function Row({ row, reviewerName, onChanged, onRemoved }: RowProps) {
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
          <td colSpan={8}>
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
  const [rows, setRows] = useState<Fundamental[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listFundamentals({ pendingOnly: true })
      .then(setRows)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }, []);

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
  if (!rows) return <SkeletonTable rows={4} columns={8} />;
  if (rows.length === 0) {
    return (
      <EmptyState title="Nothing pending.">
        <p style={{ margin: 0 }}>
          Every AI-assisted extraction has been reviewed. New figures appear here when the
          financial-statement scan reads a newly filed PDF.
        </p>
      </EmptyState>
    );
  }

  return (
    <div className="table-wrap table-scroll">
      <table className="data-table">
        <thead>
          <tr>
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
          {rows.map((r) => (
            <Row
              key={r.id}
              row={r}
              reviewerName={reviewerName}
              onChanged={(u) => setRows((p) => p?.map((x) => (x.id === u.id ? u : x)) ?? p)}
              onRemoved={(id) => setRows((p) => p?.filter((x) => x.id !== id) ?? p)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
