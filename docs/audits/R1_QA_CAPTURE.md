# R1 T4B.1 — Automated QA capture

**19/52 assertions passed.**

## Today (desktop)

Screenshot: `docs\audits\screenshots\R1\today_desktop.png`

| Assertion | Result | Detail |
|---|---|---|
| Header reads "Today's summary" | PASS |  |
| ASPI block contains three trend windows | FAIL |  |
| Earnings-yield caption is non-empty | PASS |  |
| Earnings-yield caption contains no system vocabulary | PASS |  |
| Regime block renders a classification or a quantified reason | PASS |  |
| Attention counts, where shown, are numeric and non-zero | PASS | counts seen: ['240', '35169'] |
| Portfolio block is a working link | FAIL |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 26}]

## Opportunities (desktop)

Screenshot: `docs\audits\screenshots\R1\opportunities_desktop.png`

| Assertion | Result | Detail |
|---|---|---|
| Rows render by default (<=15, real data may be fewer) | PASS | rows=6 |
| Page-size selector present | FAIL |  |
| Next/previous controls present | FAIL |  |
| No cell renders a bare dash | PASS |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 13}]

## Companies (desktop)

Screenshot: `docs\audits\screenshots\R1\companies_desktop.png`

| Assertion | Result | Detail |
|---|---|---|
| 5/10/15/30-day sort columns present | FAIL |  |
| Sort columns are functional headers | FAIL |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 9}]

## Portfolio (desktop)

Screenshot: `docs\audits\screenshots\R1\portfolio_desktop.png`

| Assertion | Result | Detail |
|---|---|---|
| Trend windows present | FAIL |  |
| "Sell Above" column present | FAIL |  |
| "Buy Below" absent | PASS |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 8}]

## Macro (desktop)

Screenshot: `docs\audits\screenshots\R1\macro_desktop.png`

| Assertion | Result | Detail |
|---|---|---|
| Every series shows real or missing status | PASS |  |
| Heat map renders (sensitivity matrix with cell shading) | PASS |  |
| Sector click opens drill-down with market-share visual | FAIL | Locator.click: Timeout 15000ms exceeded.
Call log:
  - waiting for get_by_role("button", name="Banks", exact=True).first
 |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 7}]

## Data health (desktop)

Screenshot: `docs\audits\screenshots\R1\data-health_desktop.png`

| Assertion | Result | Detail |
|---|---|---|
| Both export actions present | FAIL |  |
| Both export actions distinguishable | FAIL |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 7}]

## Company ABL.N0000 (desktop)

| Assertion | Result | Detail |
|---|---|---|
| [ABL.N0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'ABL.N0000' never appeared in the table within 20s.") |


## Company AAF.N0000 (desktop)

| Assertion | Result | Detail |
|---|---|---|
| [AAF.N0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'AAF.N0000' never appeared in the table within 20s.") |


## Company AAF.R0000 (desktop)

| Assertion | Result | Detail |
|---|---|---|
| [AAF.R0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'AAF.R0000' never appeared in the table within 20s.") |


## Company AAIC.N0000 (desktop)

| Assertion | Result | Detail |
|---|---|---|
| [AAIC.N0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'AAIC.N0000' never appeared in the table within 20s.") |


## Company ABAN.N0000 (desktop)

| Assertion | Result | Detail |
|---|---|---|
| [ABAN.N0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'ABAN.N0000' never appeared in the table within 20s.") |


## Today (mobile)

Screenshot: `docs\audits\screenshots\R1\today_mobile.png`

| Assertion | Result | Detail |
|---|---|---|
| Header reads "Today's summary" | PASS |  |
| ASPI block contains three trend windows | FAIL |  |
| Earnings-yield caption is non-empty | FAIL |  |
| Earnings-yield caption contains no system vocabulary | PASS |  |
| Regime block renders a classification or a quantified reason | PASS |  |
| Attention counts, where shown, are numeric and non-zero | PASS | counts seen: [] |
| Portfolio block is a working link | FAIL |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 4}]

## Opportunities (mobile)

Screenshot: `docs\audits\screenshots\R1\opportunities_mobile.png`

| Assertion | Result | Detail |
|---|---|---|
| Rows render by default (<=15, real data may be fewer) | PASS | rows=6 |
| Page-size selector present | FAIL |  |
| Next/previous controls present | FAIL |  |
| No cell renders a bare dash | PASS |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 2}]

## Companies (mobile)

Screenshot: `docs\audits\screenshots\R1\companies_mobile.png`

| Assertion | Result | Detail |
|---|---|---|
| 5/10/15/30-day sort columns present | FAIL |  |
| Sort columns are functional headers | FAIL |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 3}]

## Portfolio (mobile)

Screenshot: `docs\audits\screenshots\R1\portfolio_mobile.png`

| Assertion | Result | Detail |
|---|---|---|
| Trend windows present | FAIL |  |
| "Sell Above" column present | FAIL |  |
| "Buy Below" absent | PASS |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 2}]

## Macro (mobile)

Screenshot: `docs\audits\screenshots\R1\macro_mobile.png`

| Assertion | Result | Detail |
|---|---|---|
| Every series shows real or missing status | PASS |  |
| Heat map renders (sensitivity matrix with cell shading) | PASS |  |
| Sector click opens drill-down with market-share visual | FAIL | Locator.click: Timeout 15000ms exceeded.
Call log:
  - waiting for get_by_role("button", name="Banks", exact=True).first
 |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 1}]

## Data health (mobile)

Screenshot: `docs\audits\screenshots\R1\data-health_mobile.png`

| Assertion | Result | Detail |
|---|---|---|
| Both export actions present | FAIL |  |
| Both export actions distinguishable | FAIL |  |

**Accessibility floor violations:** [{"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds", "nodes": 1}]

## Company ABL.N0000 (mobile)

| Assertion | Result | Detail |
|---|---|---|
| [ABL.N0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'ABL.N0000' never appeared in the table within 20s.") |


## Company AAF.N0000 (mobile)

| Assertion | Result | Detail |
|---|---|---|
| [AAF.N0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'AAF.N0000' never appeared in the table within 20s.") |


## Company AAF.R0000 (mobile)

| Assertion | Result | Detail |
|---|---|---|
| [AAF.R0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'AAF.R0000' never appeared in the table within 20s.") |


## Company AAIC.N0000 (mobile)

| Assertion | Result | Detail |
|---|---|---|
| [AAIC.N0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'AAIC.N0000' never appeared in the table within 20s.") |


## Company ABAN.N0000 (mobile)

| Assertion | Result | Detail |
|---|---|---|
| [ABAN.N0000] surface loaded and captured | FAIL | RuntimeError("Companies row for 'ABAN.N0000' never appeared in the table within 20s.") |

