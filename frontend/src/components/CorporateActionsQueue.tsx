import { useEffect, useState } from "react";
import {
  ApiRequestError,
  confirmCorporateAction,
  listCorporateActions,
  patchCorporateActionDraft,
  rejectCorporateAction,
} from "../api";
import type { CorporateAction } from "../types";
import { EmptyState, ErrorState, SkeletonTable } from "./states";

const TYPE_LABELS: Record<CorporateAction["type"], string> = {
  dividend_cash: "Cash dividend",
  bonus_issue: "Bonus issue",
  rights_issue: "Rights issue",
  stock_split: "Stock split",
  consolidation: "Consolidation",
  delisting: "Delisting",
  suspension: "Suspension",
};

// Which numeric fields matter per action type — mirrors
// app.api.routes.corporate_actions._validate_confirmable so the form
// never asks for a field that action's maths doesn't use (§7, §P1).
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

function Row({ action, reviewerName, onChanged, onRemoved }: RowProps) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fields = FIELDS_BY_TYPE[action.type];
  const dirty = Object.keys(edits).length > 0;

  function requireName(): boolean {
    if (reviewerName.trim()) return true;
    setError("Enter your name above before confirming or rejecting.");
    return false;
  }

  async function run(fn: () => Promise<CorporateAction>, remove: boolean) {
    setBusy(true);
    setError(null);
    try {
      const updated = await fn();
      onChanged(updated);
      if (remove) onRemoved(action.id);
      else setEdits({});
    } catch (e) {
      setError(e instanceof ApiRequestError ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr>
      <th
        scope="row"
        className="mono"
        style={{ background: "none", textTransform: "none", letterSpacing: 0, fontSize: 13, fontWeight: 500, color: "var(--ink-1)" }}
      >
        {action.ticker}
      </th>
      <td className="num">{action.ex_date}</td>
      <td>{TYPE_LABELS[action.type]}</td>
      <td>
        <div className="stack-tight">
          {fields.map((field) => (
            <div key={field} className="field-inline">
              <label className="t-label" htmlFor={`ca-${action.id}-${field}`}>
                {FIELD_LABELS[field]}
              </label>
              <input
                id={`ca-${action.id}-${field}`}
                className="num input-narrow"
                type="text"
                inputMode="decimal"
                value={edits[field] ?? (action[field] as string | null) ?? ""}
                placeholder="not set"
                onChange={(e) => setEdits((p) => ({ ...p, [field]: e.target.value }))}
              />
            </div>
          ))}
          {fields.length === 0 && <span className="t-caption">No numeric inputs for this type.</span>}
        </div>
      </td>
      <td className="prose">
        {action.notes && <p className="t-caption" style={{ margin: 0 }}>{action.notes}</p>}
        {action.source_url && (
          <a className="t-caption" href={action.source_url} target="_blank" rel="noreferrer">
            source announcement
          </a>
        )}
      </td>
      <td>
        <div className="stack-tight">
          <div className="row">
            {dirty && (
              <button disabled={busy} onClick={() => run(() => patchCorporateActionDraft(action.id, edits), false)}>
                Save
              </button>
            )}
            <button
              className="btn-primary"
              disabled={busy}
              onClick={() => {
                if (!requireName()) return;
                run(async () => {
                  if (dirty) await patchCorporateActionDraft(action.id, edits);
                  return confirmCorporateAction(action.id, reviewerName.trim());
                }, true);
              }}
            >
              Confirm
            </button>
            <button
              className="btn-danger"
              disabled={busy}
              onClick={() => {
                if (!requireName()) return;
                run(() => rejectCorporateAction(action.id, reviewerName.trim()), true);
              }}
            >
              Reject
            </button>
          </div>
          {error && (
            <p className="t-caption" role="alert" style={{ color: "var(--neg-strong)", margin: 0 }}>
              {error}
            </p>
          )}
        </div>
      </td>
    </tr>
  );
}

export function CorporateActionsQueue({ reviewerName }: { reviewerName: string }) {
  const [actions, setActions] = useState<CorporateAction[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCorporateActions({ pendingOnly: true })
      .then(setActions)
      .catch((e) => setError(e instanceof ApiRequestError ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <ErrorState
        whatFailed="The corporate-actions queue could not be loaded"
        whatItAffects="This queue only."
        whatStillWorks="The fundamentals queue and every other screen."
        whatHappensNext={<>Check the API is reachable, then reload. Underlying error: {error}</>}
      />
    );
  }
  if (!actions) return <SkeletonTable rows={4} columns={6} />;
  if (actions.length === 0) {
    return (
      <EmptyState title="Nothing pending.">
        <p style={{ margin: 0 }}>
          Every scraped corporate action has been reviewed. New announcements are scanned
          automatically every trading day — check back after the next scheduled scan.
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
            <th scope="col">Ex-date</th>
            <th scope="col">Type</th>
            <th scope="col">Fields</th>
            <th scope="col">Notes</th>
            <th scope="col">Review</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((a) => (
            <Row
              key={a.id}
              action={a}
              reviewerName={reviewerName}
              onChanged={(u) => setActions((p) => p?.map((x) => (x.id === u.id ? u : x)) ?? p)}
              onRemoved={(id) => setActions((p) => p?.filter((x) => x.id !== id) ?? p)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
