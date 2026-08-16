import { useState } from "react";

const STORAGE_KEY = "cse-alpha-reviewer-name";

/**
 * Every confirm/reject action requires an `actor` name (Master Spec §5/§8
 * — every decision on this data must be attributable). Persisting it in
 * localStorage means a reviewer types their name once per browser rather
 * than once per action, without the system silently defaulting to
 * something like "admin" if it were left blank.
 */
export function useReviewerName() {
  const [name, setName] = useState(() => localStorage.getItem(STORAGE_KEY) ?? "");

  function updateName(value: string) {
    setName(value);
    localStorage.setItem(STORAGE_KEY, value);
  }

  return { name, setName: updateName };
}
