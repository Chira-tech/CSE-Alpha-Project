import { useEffect, useState } from "react";
import { ApiRequestError, confirmFundamental, listFundamentals } from "../api";
import type { Fundamental } from "../types";
import { ProvenanceChip } from "./ProvenanceChip";

interface RowProps {
  row: Fundamental;
  reviewerName: string;
  onChanged: (updated: Fundamental) => void;
  onRemoved: (id: number) => void;
}

function FundamentalRow({ row, reviewerName, onChanged, onRemoved }: RowProps) {
  const [value, setValue] = useState(row.value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSnippet, setShowSnippet] = useState(false);
  const corrected = value !== row.value;

  async function handleConfirm() {
    if (!reviewerName.trim()) {
      setError("Enter your name above before confirming.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await confirmFundamental(row.id, reviewerName.trim(), corrected ? value : undefined);
      onChanged(updated);
      onRemoved(row.id);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Failed to confirm");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <tr>
        <td className="mono">{row.ticker}</td>
        <td className="num">{row.period_end}</td>
        <td>{row.period_type}</td>
        <td className="mono">{row.statement_line}</td>
        <td>
          <input
            className="num"
            type="text"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          {corrected && <span className="corrected-badge">corrected</span>}
        </td>
        <td>
          <ProvenanceChip tier={row.provenance_tier} />
        </td>
        <td>
          {row.source_snippet && (
            <button type="button" className="btn-link" onClick={() => setShowSnippet((s) => !s)}>
              {showSnippet ? "hide source" : "show source"}
            </button>
          )}
        </td>
        <td className="actions-cell">
          <button type="button" className="btn-confirm" onClick={handleConfirm} disabled={saving}>
            Confirm
          </button>
          {error && <p className="error-text">{error}</p>}
        </td>
      </tr>
      {showSnippet && (
        <tr>
          <td colSpan={8}>
            <pre className="snippet">{row.source_snippet}</pre>
            {row.source_url && (
              <a href={row.source_url} target="_blank" rel="noreferrer">
                view PDF{row.source_page !== null ? ` (page ${row.source_page + 1})` : ""}
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
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    listFundamentals({ pendingOnly: true })
      .then(setRows)
      .catch((e) => setLoadError(e instanceof ApiRequestError ? e.message : "Failed to load"));
  }, []);

  function handleChanged(updated: Fundamental) {
    setRows((prev) => prev?.map((r) => (r.id === updated.id ? updated : r)) ?? prev);
  }

  function handleRemoved(id: number) {
    setRows((prev) => prev?.filter((r) => r.id !== id) ?? prev);
  }

  if (loadError) return <p className="error-text">Couldn't load fundamentals: {loadError}</p>;
  if (rows === null) return <p className="muted">Loading…</p>;
  if (rows.length === 0) {
    return <p className="muted">Nothing pending. Every AI-assisted extraction has been reviewed.</p>;
  }

  return (
    <table className="queue-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Period end</th>
          <th>Type</th>
          <th>Line</th>
          <th>Value</th>
          <th>Provenance</th>
          <th>Source</th>
          <th>Review</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <FundamentalRow
            key={row.id}
            row={row}
            reviewerName={reviewerName}
            onChanged={handleChanged}
            onRemoved={handleRemoved}
          />
        ))}
      </tbody>
    </table>
  );
}
