# Fundamentals queue release — 2026-08-30

Released **477 rows** with `period_end >= 2021-01-01` across **41 tickers**, tagged `auto:released-from-queue-v1`.

## What this is, honestly

This is NOT a verified confirmation. Everything that passed a correctness check was already promoted by `auto-confirm-fundamentals`, and everything a third party could adjudicate was already handled by `external_crosscheck.py`. What remains is the set that failed a check — **219 of these 477 rows sit on a filing that does not satisfy an accounting identity**. Releasing them trades data quality for coverage so the engine and the web app can be exercised. Every row carries a dated note saying so, and `--revert --apply` undoes the whole pass.

Pre-2021 rows were deliberately left queued: measured separately, they unlock no additional valuation (median confirmed depth is already 39 periods per ticker) and add only trend depth.

## By year

| year | rows |
|---|---|
| 2023 | 25 |
| 2024 | 33 |
| 2025 | 135 |
| 2026 | 284 |

## By statement line

| line | rows |
|---|---|
| operating_profit | 38 |
| cost_of_sales | 37 |
| capital_expenditure | 37 |
| revenue | 29 |
| profit_before_tax | 29 |
| cash_generated_from_operations | 25 |
| gross_profit | 22 |
| total_equity | 22 |
| total_liabilities | 21 |
| income_tax_expense | 20 |
| depreciation_expense | 20 |
| amortisation_expense | 19 |
| total_assets | 17 |
| total_comprehensive_income | 17 |
| interest_expense | 16 |
| total_equity_and_liabilities | 14 |
| trade_payables | 11 |
| operating_profit_before_working_capital_changes | 11 |
| net_income | 11 |
| total_current_liabilities | 10 |
| total_non_current_assets | 9 |
| total_current_assets | 9 |
| inventories | 7 |
| revaluation_reserves | 7 |
| trade_receivables | 6 |
| total_non_current_liabilities | 6 |
| total_interest_bearing_debt | 5 |
| cash_and_cash_equivalents | 1 |
| bank_overdraft | 1 |
