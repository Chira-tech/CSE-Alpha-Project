/**
 * P1.1's own rule: "On completion, invalidate the query cache so the
 * screens refresh with new data — do NOT force a page reload." This
 * project has no query-cache library (no react-query, no SWR — see
 * package.json), so there is no cache to invalidate; this is the
 * smallest real substitute, a plain subscribe/publish pair a mounted
 * screen can opt into.
 *
 * Scope, stated plainly rather than silently assumed: only
 * `DataHealthScreen` subscribes today, because it is the one screen
 * whose own content (job history, freshness) is directly about what
 * `RunCapture` just did. Wiring every other screen (Companies, Today,
 * Macro, ...) to refetch on every job completion is real, separate work
 * — not done here, not claimed as done.
 */

type Listener = () => void;

const listeners = new Set<Listener>();

export function onDataRefreshed(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function notifyDataRefreshed(): void {
  for (const fn of listeners) fn();
}
