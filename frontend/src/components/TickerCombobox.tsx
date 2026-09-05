import { useEffect, useId, useRef, useState } from "react";
import { ApiRequestError, listSecurities } from "../api";
import { formatPrice, UNAVAILABLE } from "../format";
import type { SecurityListItem } from "../types";

const MAX_RESULTS = 8;
const DEBOUNCE_MS = 150;

/** Ranks the server's substring matches so the most useful row is first:
 * exact ticker prefix, then company-name prefix, then everything else
 * (already substring-filtered server-side), each group alphabetical. */
function rank(items: SecurityListItem[], query: string): SecurityListItem[] {
  const q = query.trim().toLowerCase();
  function tier(item: SecurityListItem): number {
    if (item.ticker.toLowerCase().startsWith(q)) return 0;
    if (item.name.toLowerCase().startsWith(q)) return 1;
    return 2;
  }
  return [...items].sort((a, b) => tier(a) - tier(b) || a.ticker.localeCompare(b.ticker)).slice(0, MAX_RESULTS);
}

/**
 * A ticker/company search box shared wherever a ticker is entered —
 * starts with the Journal's decision form. Suggests from the same
 * `/securities` list every other screen reads (one security master, no
 * separate ad hoc list), so what appears here is exactly what the app
 * already knows about, never an invented match.
 *
 * Deliberately does NOT enforce selection itself — the caller decides
 * whether free text is acceptable (the Journal requires a real match;
 * a future looser use might not).
 */
export function TickerCombobox({
  id,
  value,
  onChange,
  onSelect,
  placeholder,
  required,
}: {
  id: string;
  /** The raw text currently in the field. */
  value: string;
  /** Fired on every keystroke, including free text that matches nothing. */
  onChange: (text: string) => void;
  /** Fired only when a real row is chosen — the caller's signal that
   * `value` now names a real, confirmed security. */
  onSelect: (item: SecurityListItem) => void;
  placeholder?: string;
  required?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<SecurityListItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const requestSeq = useRef(0);

  useEffect(() => {
    const query = value.trim();
    clearTimeout(debounceRef.current);
    if (query.length < 1) {
      setResults(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    const seq = ++requestSeq.current;
    debounceRef.current = setTimeout(() => {
      listSecurities(query)
        .then((items) => {
          if (requestSeq.current !== seq) return; // a newer keystroke already superseded this
          setResults(rank(items, query));
          setActiveIndex(-1);
        })
        .catch((e) => {
          if (requestSeq.current !== seq) return;
          setResults([]);
          if (!(e instanceof ApiRequestError)) throw e;
        })
        .finally(() => {
          if (requestSeq.current === seq) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => clearTimeout(debounceRef.current);
  }, [value]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function choose(item: SecurityListItem) {
    onSelect(item);
    setOpen(false);
    setResults(null);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || !results || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      if (activeIndex >= 0) {
        e.preventDefault();
        choose(results[activeIndex]);
      }
    } else if (e.key === "Tab") {
      if (activeIndex >= 0) choose(results[activeIndex]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const showPanel = open && value.trim().length > 0;

  return (
    <div className="combobox" ref={rootRef}>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={showPanel}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={activeIndex >= 0 ? `${listboxId}-opt-${activeIndex}` : undefined}
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        required={required}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {showPanel && (
        <div className="combobox-panel" role="listbox" id={listboxId}>
          {loading && !results ? (
            <div className="combobox-row combobox-row-static">
              <span className="skeleton skeleton-line" style={{ width: "70%" }} />
            </div>
          ) : !results || results.length === 0 ? (
            <div className="combobox-row combobox-row-static t-caption">
              No match for "{value.trim()}" in the security list.
            </div>
          ) : (
            results.map((item, i) => (
              <button
                type="button"
                key={item.ticker}
                id={`${listboxId}-opt-${i}`}
                role="option"
                aria-selected={i === activeIndex}
                className={`combobox-row${i === activeIndex ? " combobox-row-active" : ""}`}
                onMouseEnter={() => setActiveIndex(i)}
                onClick={() => choose(item)}
              >
                <span className="combobox-row-top">
                  <strong className="mono">{item.ticker}</strong>
                  <span className="combobox-row-name">{item.name}</span>
                  {item.cse_sector && <span className="t-caption combobox-row-sector">{item.cse_sector}</span>}
                </span>
                <span className="combobox-row-bottom t-caption">
                  {item.last_close !== null ? formatPrice(item.last_close) : UNAVAILABLE}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
