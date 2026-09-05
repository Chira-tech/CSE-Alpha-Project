import { useState } from "react";
import { ApiRequestError, login } from "../api";

/**
 * The gate `App` renders instead of the product whenever `GET /auth/
 * status` (see `app.security`'s own module docstring on the backend for
 * the full threat model) says a password is required and this browser
 * hasn't supplied it yet. A single shared password, not an account
 * system — this product has exactly one intended user.
 */
export function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(password);
      onSuccess();
    } catch (err) {
      if (err instanceof ApiRequestError) {
        setError(err.message);
        const retry = (err.detail as { retry_after?: number } | undefined)?.retry_after;
        setRetryAfter(typeof retry === "number" ? retry : null);
      } else {
        setError("Could not reach the server.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--canvas)",
      }}
    >
      <form onSubmit={submit} className="card stack-tight" style={{ width: 320 }}>
        <h1 className="t-display" style={{ margin: 0, fontSize: 22 }}>
          CSE Alpha Engine
        </h1>
        <p className="t-body prose" style={{ margin: 0, color: "var(--ink-3)" }}>
          This is a personal tool — enter the password to continue.
        </p>
        <label className="field">
          <span className="t-label">Password</span>
          <input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        {error && (
          <p className="t-caption" style={{ color: "var(--neg-strong)", margin: 0 }}>
            {error}
            {retryAfter ? ` Try again in ${Math.ceil(retryAfter / 60)} min.` : ""}
          </p>
        )}
        <button type="submit" className="btn-primary" disabled={busy || !password}>
          {busy ? "Checking…" : "Enter"}
        </button>
      </form>
    </div>
  );
}
