import { useId, useState } from "react";

/**
 * Tap-to-open equivalent of a hover-only `title` tooltip (mobile spec
 * §7 — "any hover-only tooltip needs a tap-to-open equivalent on touch
 * devices"). Wraps a chip/badge that already carries its own `title`
 * for desktop hover; this adds a small popover toggled by tap/click/
 * Enter, so the same explanation reaches a phone with no working
 * `:hover`. Desktop is unaffected in its default (unclicked) state —
 * the wrapped element renders exactly as it did before.
 */
export function TapTip({
  label,
  children,
  enlargeHitArea = false,
}: {
  label: string;
  children: React.ReactNode;
  /** Pads the tappable area on mobile (equal negative margin keeps the
   * visible size unchanged) for chips too small to be a 44px target on
   * their own, e.g. `ProvenanceDot`'s 8px dot. */
  enlargeHitArea?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();

  if (!label) return <>{children}</>;

  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <span
        className={enlargeHitArea ? "tap-tip-hit" : undefined}
        tabIndex={0}
        role="button"
        aria-describedby={open ? id : undefined}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        {children}
      </span>
      {open && (
        <span
          role="tooltip"
          id={id}
          className="tap-tip-bubble"
          onClick={(e) => e.stopPropagation()}
        >
          {label}
        </span>
      )}
    </span>
  );
}
