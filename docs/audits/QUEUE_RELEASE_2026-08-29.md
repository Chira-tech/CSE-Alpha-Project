# Fundamentals queue release — 2026-08-29

Released **3870 rows** with `period_end >= 2021-01-01` across **201 tickers**, tagged `auto:released-from-queue-v1`.

## What this is, honestly

This is NOT a verified confirmation. Everything that passed a correctness check was already promoted by `auto-confirm-fundamentals`, and everything a third party could adjudicate was already handled by `external_crosscheck.py`. What remains is the set that failed a check — **3227 of these 3870 rows sit on a filing that does not satisfy an accounting identity**. Releasing them trades data quality for coverage so the engine and the web app can be exercised. Every row carries a dated note saying so, and `--revert --apply` undoes the whole pass.

Pre-2021 rows were deliberately left queued: measured separately, they unlock no additional valuation (median confirmed depth is already 39 periods per ticker) and add only trend depth.

## By year

| year | rows |
|---|---|
| 2021 | 645 |
| 2022 | 790 |
| 2023 | 669 |
| 2024 | 715 |
| 2025 | 709 |
| 2026 | 342 |

## By statement line

| line | rows |
|---|---|
| revenue | 281 |
| trade_receivables | 278 |
| profit_before_tax | 237 |
| net_income | 227 |
| cost_of_sales | 225 |
| trade_payables | 222 |
| gross_profit | 210 |
| income_tax_expense | 199 |
| interest_expense | 193 |
| revaluation_reserves | 158 |
| total_assets | 147 |
| total_comprehensive_income | 133 |
| inventories | 132 |
| total_equity | 131 |
| total_interest_bearing_debt | 127 |
| total_liabilities | 125 |
| total_non_current_assets | 118 |
| operating_profit_before_working_capital_changes | 113 |
| cash_generated_from_operations | 102 |
| total_non_current_liabilities | 91 |
| total_equity_and_liabilities | 73 |
| depreciation_expense | 66 |
| total_current_assets | 62 |
| capital_expenditure | 59 |
| operating_profit | 56 |
| total_current_liabilities | 47 |
| assets_held_for_sale | 25 |
| amortisation_expense | 12 |
| net_working_capital | 11 |
| advances_and_prepayments | 6 |
| net_increase_in_cash | 2 |
| change_in_net_working_capital | 2 |
