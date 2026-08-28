// M5 — Convergence Engine & Playbook System (docs/CLAUDE_CODE_BRIEF_M5.md).
// Task 5+ adds the real types here (BaseRateResponse with its mandatory
// `null` field, playbook report cards, trial records, ...). Only the
// Task 1 isolation-scaffold status shape exists so far.

export interface M5Status {
  m5_enabled: boolean;
  database_url: string;
}
