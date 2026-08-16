import { useEffect, useState } from "react";
import {
  ApiRequestError,
  confirmCorporateAction,
  listCorporateActions,
  patchCorporateActionDraft,
  rejectCorporateAction,
} from "../api";
import type { CorporateAction } from "../types";

const TYPE_LABELS: Record<CorporateAction["type"], string> = {
  dividend_cash: "Cash dividend",
  bonus_issue: "Bonus issue",
  rights_issue: "Rights issue",
  stock_split: "Stock split",
  consolidation: "Consolidation",
  delisting: "Delisting",
  suspension: "Suspension",
};

// Which numeric fields are relevant/editable per action type — matches
// app.api.routes.corporate_actions._validate_confirmable's requirements
// (Master Spec §7 / Appendix P1) so the form never asks a reviewer to
// fill in a field that isn't actually used for that action's maths.
const FIELDS_BY_TYPE: Record<CorporateAction["type"], (keyof CorporateAction)[]> = {
  dividend_cash: ["cash_amount"],
  bonus_issue: ["ratio"],
  stock_split: ["ratio"],
  consolidation: ["ratio"],
  rights_issue: ["ratio", "subscription_price", "cum_rights_price"],
  delisting: [],
  suspension: [],
};

const FIELD_LABELS: Partial<Record<keyof CorporateAction, string>> = {
  ratio: "Ratio (new per held)",
  cash_amount: "Cash amount / share",
  subscription_price: "Subscription price",
  cum_rights_price: "Cum-rights price",
};

interface RowProps {
  action: CorporateAction;
  reviewerName: string;
  onChanged: (updated: CorporateAction) => void;
  onRemoved: (id: number) => void;
}

function CorporateActionRow({ action, reviewerName, onChanged, onRemoved }: RowProps) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fields = FIELDS_BY_TYPE[action.type];
  const dirty = Object.keys(edits).length > 0;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await patchCorporateActionDraft(action.id, edits);
      onChanged(updated);
      setEdits({});
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleConfirm() {
    if (!reviewerName.trim()) {
      setError("Enter your name above before confirming.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (dirty) await patchCorporateActionDraft(action.id, edits);
      const updated = await confirmCorporateAction(action.id, reviewerName.trim());
      onChanged(updated);
      onRemoved(action.id);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Failed to confirm");
    } finally {
      setSaving(false);
    }
  }

  async function handleReject() {
    if (!reviewerName.trim()) {
      setError("Enter your name above before rejecting.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await rejectCorporateAction(action.id, reviewerName.trim());
      onChanged(updated);
      onRemoved(action.id);
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Failed to reject");
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr>
      <td className="mono">{action.ticker}</td>
      <td className="num">{action.ex_date}</td>
      <td>{TYPE_LABELS[action.type]}</td>
      <td colSpan={fields.length ? undefined : 1}>
        <div className="field-grid">
          {fields.map((field) => (
            <label key={field} className="field">
              <span className="field-label">{FIELD_LABELS[field]}</span>
              <input
                className="num"
                type="text"
                inputMode="decimal"
                value={edits[field] ?? (action[field] as string | null) ?? ""}
                placeholder="—"
                onChange={(e) => setEdits((prev) => ({ ...prev, [field]: e.target.value }))}
              />
            </label>
          ))}
        </div>
      </td>
      <td className="notes-cell">
        {action.notes && <p className="notes-text">{action.notes}</p>}
        {action.source_url && (
          <a href={action.source_url} target="_blank" rel="noreferrer">
            source
          </a>
        )}
      </td>
      <td className="actions-cell">
        {dirty && (
          <button type="button" onClick={handleSave} disabled={saving}>
            Save
          </button>
        )}
        <button type="button" className="btn-confirm" onClick={handleConfirm} disabled={saving}>
          Confirm
        </button>
        <button type="button" className="btn-reject" onClick={handleReject} disabled={saving}>
          Reject
        </button>
        {error && <p className="error-text">{error}</p>}
      </td>
    </tr>
  );
}

export function CorporateActionsQueue({ reviewerName }: { reviewerName: string }) {
  const [actions, setActions] = useState<CorporateAction[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    listCorporateActions({ pendingOnly: true })
      .then(setActions)
      .catch((e) => setLoadError(e instanceof ApiRequestError ? e.message : "Failed to load"));
  }, []);

  function handleChanged(updated: CorporateAction) {
    setActions((prev) => prev?.map((a) => (a.id === updated.id ? updated : a)) ?? prev);
  }

  function handleRemoved(id: number) {
    setActions((prev) => prev?.filter((a) => a.id !== id) ?? prev);
  }

  if (loadError) return <p className="error-text">Couldn't load corporate actions: {loadError}</p>;
  if (actions === null) return <p className="muted">Loading…</p>;
  if (actions.length === 0) {
    return <p className="muted">Nothing pending. Every scraped corporate action has been reviewed.</p>;
  }

  return (
    <table className="queue-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Ex-date</th>
          <th>Type</th>
          <th>Fields</th>
          <th>Notes / source</th>
          <th>Review</th>
        </tr>
      </thead>
      <tbody>
        {actions.map((action) => (
          <CorporateActionRow
            key={action.id}
            action={action}
            reviewerName={reviewerName}
            onChanged={handleChanged}
            onRemoved={handleRemoved}
          />
        ))}
      </tbody>
    </table>
  );
}
