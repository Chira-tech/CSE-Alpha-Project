// M5 — Convergence Engine & Playbook System. Deliberately self-contained
// — reads the SAME `VITE_API_BASE_URL` env var the app's own `src/api.ts`
// does (both hit the one real backend process; `/api/v5` is just a
// different router prefix on it, not a separate service), but does not
// import that module, keeping this feature's own dependency boundary
// clean per the brief's isolation rules.
import type { M5Status } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function getM5Status(): Promise<M5Status> {
  const res = await fetch(`${BASE_URL}/api/v5/status`);
  if (!res.ok) throw new Error(`M5 status check failed: ${res.status}`);
  return res.json();
}
