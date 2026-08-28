"""Task 4 (brief §4) — Appendix A's exact primary-state and modifier
thresholds. NOT YET IMPLEMENTED, and not a stub that can be filled from
this brief alone: Appendix A lives in the companion spec PDF (`CSE Alpha
Engine - M5 Convergence Engine v1.0.pdf`), which is referenced but not
included in `docs/CLAUDE_CODE_BRIEF_M5.md`'s own text. Inventing
threshold numbers here rather than sourcing them from that document
would be exactly the kind of confident-but-fake content this whole
project's own discipline (§8, and every module's own "never guess"
rule) exists to avoid. Provide that PDF's Appendix A content (or the
specific numbers) before this file can be built for real.

Known from the brief itself, not invented (§0.5 D1(a) — this OVERRIDES
whatever the PDF's own original grid was):

    VALUATION GAP (revised, 3 levels — not 4)
      Deep        price / fv <= 0.70
      Moderate    0.70 - 0.90
      Not cheap   > 0.90          (replaces the PDF's separate Fair/Rich)

The other two axes of the 3x3 primary grid (9 states total) and every
modifier's own threshold are NOT in the brief text and must come from
Appendix A directly.
"""
