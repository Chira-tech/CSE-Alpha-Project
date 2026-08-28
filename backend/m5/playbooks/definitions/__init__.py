"""Task 7 (brief §7) — PB-01 through PB-06, one module each, per
Appendix B of the companion spec PDF. Appendix B's real content is not
in `docs/CLAUDE_CODE_BRIEF_M5.md`'s own text (only PB-02's own example
is quoted there, as an illustration of the declarative `Playbook(...)`
shape, not as PB-02's actual final definition) — the other five
playbooks' entry/exit conditions and priors need that document. Not yet
implemented. ALL SIX must be registered in `m5.trials` with their
mechanisms BEFORE any backtest runs (brief §7's own explicit ordering
requirement) — this is the reason `registry.py` exists as a separate
step from `evaluator.py`, not a detail to lose once these are written."""
