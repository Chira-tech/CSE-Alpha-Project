# CSE Alpha Engine --- System-Wide Valuation & Decision Engine Upgrade

## Purpose

This document is an implementation specification for Claude to upgrade
the **entire CSE Alpha Engine**, not a single security.

The goal is to make valuation, fair value ranges, buy prices, sell
prices, scenario analysis, data-quality handling, and investment
recommendations:

-   calculated automatically inside the system;
-   applicable consistently across the full CSE security universe;
-   driven by security-specific data and archetype/routing rules;
-   transparent and auditable;
-   conservative when data is missing;
-   resistant to false precision;
-   suitable for both profitable companies and loss-making/turnaround
    companies;
-   capable of producing an actionable price ladder rather than one
    unexplained fair-value number.

**Important:** DPL is the example that exposed the weaknesses below. Do
NOT hard-code DPL-specific rules, prices, weights, or fixes. Build
reusable system-level functionality and let DPL emerge from the same
engine.

------------------------------------------------------------------------

# 1. Current-System Limitations Identified

The current DPL output demonstrates several architectural limitations.

## 1.1 Single-number fair value creates false precision

The system currently produces a triangulated fair value such as:

-   Justified P/B: 12.52
-   Residual Income: 12.52
-   FCFF DCF: 50.99
-   Triangulated Blend: 22.70

The problem is not that these numbers cannot be calculated.

The problem is that the system does not sufficiently explain:

1.  why each model applies;
2.  what weight each model receives;
3.  which assumptions drive each model;
4.  how uncertainty is measured;
5.  whether the business is profitable enough for the model to be
    reliable;
6.  whether the result is a base-case value, turnaround value,
    liquidation value, or optimistic terminal value.

### Required improvement

Every valuation output must contain:

-   method;
-   applicability status;
-   data completeness;
-   confidence score;
-   assumptions;
-   result;
-   assigned weight;
-   contribution to blended value;
-   reason for inclusion/exclusion.

------------------------------------------------------------------------

# 2. Valuation Must Be Archetype-Aware

The engine must classify each security into a valuation archetype before
deciding which models to use.

Suggested archetypes:

1.  Profitable mature company
2.  High-growth company
3.  Cyclical company
4.  Turnaround / distressed company
5.  Asset-heavy company
6.  Financial institution
7.  REIT / property company
8.  Holding / investment company
9.  Commodity/resource company
10. Early-stage / low-earnings company
11. Dividend-oriented company
12. Conglomerate / diversified company

A company can have more than one characteristic, but the engine should
assign:

-   `primary_archetype`
-   `secondary_archetypes`
-   `valuation_profile`

The valuation profile determines model routing and weights.

Do not apply the same valuation formula equally to every security.

------------------------------------------------------------------------

# 3. Replace "Which Models Apply?" With a Formal Routing Engine

Create a central valuation-routing function.

Conceptually:

``` text
valuation_router(security, financials, market_data, sector_data)
    -> applicable_models
    -> blocked_models
    -> confidence
    -> required_missing_data
    -> recommended_weights
```

For every model, return:

``` text
model
status
reason
data_completeness
model_confidence
recommended_weight
```

Possible statuses:

-   `PRIMARY`
-   `SUPPORTING`
-   `CONDITIONAL`
-   `BLOCKED`
-   `NOT_MEANINGFUL`

Examples:

### P/E

BLOCKED when:

-   current earnings are negative;
-   normalized earnings cannot be estimated reliably;
-   earnings history is insufficient.

Do not simply display "data unavailable."

Display why it is unavailable.

### EV/EBITDA

CONDITIONAL when:

-   EBITDA is positive and meaningful;
-   debt is material but manageable;
-   EBITDA is not distorted by one-off items.

BLOCKED when EBITDA is negative or structurally unreliable.

### DCF

CONDITIONAL / LOW CONFIDENCE when:

-   historical FCFF is unstable;
-   current profitability is negative;
-   turnaround assumptions are required.

### P/B

PRIMARY for:

-   asset-heavy companies;
-   financials;
-   companies with meaningful tangible book value.

But adjust for poor asset quality where necessary.

### Residual Income

PRIMARY only when:

-   book value is meaningful;
-   ROE and cost of equity can be estimated;
-   forecasts are credible.

### Dividend models

BLOCKED if there is no reliable dividend history.

### SOTP

PRIMARY for:

-   conglomerates;
-   holding companies;
-   businesses with clearly separable assets/segments.

------------------------------------------------------------------------

# 4. Build a Real Multi-Layer Valuation Framework

The engine should not output only one intrinsic value.

It should calculate at least four independent valuation layers.

## Layer A --- Asset / Balance-Sheet Value

Calculate:

-   reported book value per share;
-   tangible book value per share;
-   adjusted NAV per share;
-   conservative NAV;
-   liquidation-style NAV where appropriate.

### Asset haircuts

Haircuts should be systematic and sector-aware.

Example framework:

``` text
Cash                    100%
Receivables             70–100%
Inventory               50–100%
Investment property     70–100%
PP&E                    50–100%
Intangibles               0–50%
Other assets            security-specific
```

Do NOT hard-code one haircut for every company.

Use:

-   historical realization;
-   sector;
-   asset type;
-   days inventory;
-   receivable aging;
-   impairment history;
-   auditor/accounting information;
-   management disclosures.

Output:

``` text
Reported NAV
Adjusted NAV
Conservative NAV
NAV confidence
```

------------------------------------------------------------------------

# 5. Layer B --- Normalized Earnings Valuation

This is essential for companies where current earnings are distorted by
a downturn or temporary loss.

Do not use only the latest year's EPS.

Calculate normalized earnings from available history.

Suggested methodology:

1.  collect 5--10 years of annual earnings where available;
2.  identify abnormal years;
3.  calculate median EPS;
4.  calculate normalized operating margin;
5.  calculate normalized tax rate;
6.  calculate normalized interest burden;
7.  calculate normalized net margin;
8.  incorporate current revenue level;
9.  apply sector-appropriate normalized P/E.

The engine should produce:

``` text
Reported EPS
Normalized EPS
Conservative EPS
Base EPS
Bull EPS
Applied P/E
Earnings Value / Share
```

For companies with insufficient history:

``` text
NORMALIZED_EARNINGS_CONFIDENCE = LOW
```

and reduce its valuation weight.

------------------------------------------------------------------------

# 6. Layer C --- DCF / FCFF

Keep DCF, but change its role.

DCF must be an explicit scenario model, not an automatic source of a
high fair value.

Calculate:

-   historical revenue CAGR;
-   historical operating margin;
-   normalized operating margin;
-   revenue growth distribution;
-   EBITDA margin;
-   EBIT margin;
-   tax rate;
-   capex;
-   depreciation;
-   working-capital investment;
-   FCFF;
-   WACC;
-   terminal growth;
-   terminal value;
-   enterprise value;
-   net debt;
-   equity value;
-   value per share.

## Critical requirement: Reverse DCF

Also calculate:

> "What future operating performance is required for today's market
> price to be justified?"

For each security, show:

``` text
Current price
Implied enterprise value
Required revenue CAGR
Required terminal margin
Required ROIC
Required FCFF
Required terminal growth
```

This prevents a DCF from looking attractive simply because optimistic
assumptions were entered.

------------------------------------------------------------------------

# 7. DCF Confidence Score

Every DCF must have a confidence score.

Suggested components:

-   earnings stability;
-   FCFF stability;
-   revenue history;
-   margin history;
-   forecast coverage;
-   debt risk;
-   cyclicality;
-   terminal-value dependency;
-   data completeness.

Output:

``` text
DCF Value: 50.99
DCF Confidence: LOW
Terminal Value Dependency: HIGH
Forecast Risk: HIGH
```

Do not allow a low-confidence DCF to dominate the final valuation.

------------------------------------------------------------------------

# 8. Layer D --- Market / Relative Valuation

Calculate peer-relative valuation automatically.

Possible multiples:

-   P/E
-   P/B
-   EV/EBITDA
-   EV/Sales
-   P/S
-   dividend yield
-   FCF yield

For every multiple:

-   sector median;
-   sector 25th percentile;
-   sector 75th percentile;
-   company historical median;
-   company current multiple;
-   premium/discount to sector;
-   premium/discount to own history.

Use only meaningful multiples.

For example:

``` text
Negative EPS -> P/E excluded
Negative EBITDA -> EV/EBITDA excluded
No dividend -> dividend yield excluded
```

------------------------------------------------------------------------

# 9. Final Valuation Must Be a RANGE

Stop treating intrinsic value as one exact number.

Every security should have:

``` text
Bear Value
Base Value
Bull Value
Central Fair Value
Fair Value Range
Confidence
```

Example:

``` text
Conservative / Bear: 11.50
Base:                15.50
Bull / Turnaround:   22.00
Central estimate:    15.40
```

The exact numbers must be generated by the engine.

------------------------------------------------------------------------

# 10. Fix Scenario Logic

There is currently a serious scenario-labeling problem.

An example output showed:

``` text
BEAR  -15.06
BASE   50.99
BULL   12.52
```

This is logically inverted.

The system must enforce:

``` text
BEAR <= BASE <= BULL
```

before displaying any scenario result.

Add a validation rule:

``` python
assert bear_value <= base_value <= bull_value
```

If the condition fails:

-   do not display the results as valid;
-   flag the valuation engine;
-   identify which component caused the inversion;
-   automatically reorder only if the values are genuinely scenario
    values and not mislabeled model outputs;
-   otherwise return an error requiring correction.

Do not silently hide the error.

------------------------------------------------------------------------

# 11. Separate Valuation Anchors From Scenarios

This distinction is critical.

These are NOT the same thing:

``` text
P/B value
DCF value
Residual Income value
```

versus:

``` text
Bear case
Base case
Bull case
```

A DCF result of 50.99 is a MODEL OUTPUT.

It is not automatically the BULL CASE.

A P/B value of 12.52 is a MODEL OUTPUT.

It is not automatically the BEAR CASE.

Build a separate scenario engine that takes model outputs and operating
assumptions and produces:

``` text
Bear
Base
Bull
```

------------------------------------------------------------------------

# 12. Transparent Blending

The system currently produces a blended value such as 22.70 without
making the weighting sufficiently obvious.

This must change.

Display:

  ------------------------------------------------------------------------
  Method                Value         Weight   Contribution     Confidence
  ------------ -------------- -------------- -------------- --------------
  Adjusted NAV     calculated     calculated     calculated   High/Med/Low

  Normalized       calculated     calculated     calculated   High/Med/Low
  Earnings                                                  

  DCF              calculated     calculated     calculated   High/Med/Low

  Relative         calculated     calculated     calculated   High/Med/Low
  Valuation                                                 
  ------------------------------------------------------------------------

Then:

``` text
Weighted Fair Value =
SUM(method_value * method_weight)
```

Weights must equal 100%.

The weights should be generated from the valuation profile and
confidence scores.

------------------------------------------------------------------------

# 13. Dynamic Model Weighting

Do not hard-code the same weights for all securities.

Example:

## Profitable mature company

``` text
Normalized Earnings      35%
DCF                       30%
Relative Valuation        20%
NAV                       15%
```

## Asset-heavy company

``` text
Adjusted NAV              40%
Normalized Earnings       25%
DCF                       20%
Relative Valuation        15%
```

## Turnaround company

``` text
Adjusted NAV              35%
Normalized Earnings       30%
DCF                       15%
Relative Valuation        20%
```

## Financial institution

Use a different profile, e.g.:

``` text
P/B / Residual Income
ROE
Cost of Equity
Asset quality
Capital adequacy
Dividend capacity
```

The exact weights should be configurable in the system, documented, and
testable.

------------------------------------------------------------------------

# 14. Calculate Buy Price Automatically

The system should not stop at fair value.

Create:

``` text
buy_price_engine()
```

Inputs:

-   central fair value;
-   bear value;
-   confidence;
-   valuation dispersion;
-   earnings risk;
-   balance-sheet risk;
-   liquidity;
-   volatility;
-   data completeness;
-   desired margin of safety.

Output:

``` text
Exceptional Buy
Strong Buy
Accumulate
Fair
Overvalued
Avoid
```

## Core formula

At minimum:

``` text
Buy Price =
Central Fair Value × (1 - Required Margin of Safety)
```

But required MOS must be dynamic.

Example:

### High-quality, profitable, stable

MOS: 15--20%

### Average company

MOS: 20--25%

### Cyclical

MOS: 25--30%

### Turnaround / loss-making

MOS: 30--40%+

### Low-confidence / poor data

MOS: higher or NO BUY

The system should calculate the required MOS instead of asking the user
to guess.

------------------------------------------------------------------------

# 15. Calculate Multiple Buy Zones

Every security should have a price ladder.

Example:

``` text
< X                 Exceptional Buy
X – Y               Strong Buy
Y – Z               Accumulate
Z – Fair Value      Hold
Fair – Bull Value   Reduce
> Bull Value        Sell
```

The actual levels must be calculated.

Do not hard-code DPL's prices.

------------------------------------------------------------------------

# 16. Calculate Sell Price Automatically

Do not use one universal sell price.

Create:

``` text
take_profit_price
fair_value_price
bull_value_price
overvaluation_price
```

Example logic:

### Partial profit

When price reaches:

``` text
Base fair value
```

### Major profit-taking

When price reaches:

``` text
Bull value
```

### Strong sell

When price exceeds:

``` text
Bull value + valuation premium
```

subject to fundamentals.

------------------------------------------------------------------------

# 17. Fundamental Exit Rules

The system should calculate thesis-break conditions.

Examples:

``` text
Revenue deterioration > X% for Y periods
Gross margin deterioration > X bps
Operating margin below threshold
Net debt/EBITDA above threshold
Interest coverage below threshold
Equity destruction
CFO negative for X periods
Dividend suspension
Material dilution
Auditor qualification
Going-concern warning
```

These thresholds should be sector-aware.

A price stop alone is not sufficient.

------------------------------------------------------------------------

# 18. Price-Based vs Fundamental-Based Exits

Separate:

### Valuation exit

The share became expensive.

### Fundamental exit

The investment thesis deteriorated.

### Risk exit

Balance-sheet/liquidity risk became unacceptable.

### Technical exit

Momentum/market structure broke.

Do not combine these into one opaque "sell" score.

------------------------------------------------------------------------

# 19. Margin of Safety Calculation Must Be Correct

The system currently displays a 31% MOS while the current price and fair
value imply a different figure.

This needs to be fixed.

For current price:

``` text
Current MOS =
1 - Current Price / Central Fair Value
```

Also calculate:

``` text
Buy Price MOS =
1 - Buy Price / Central Fair Value
```

Display both separately.

Example:

``` text
Central Fair Value: 22.70
Current Price:      13.40
Current MOS:        40.97%

Recommended Buy:    12.50
Buy Price MOS:      44.93%
```

Do not label one as the other.

------------------------------------------------------------------------

# 20. Valuation Dispersion

The engine should calculate how much the models disagree.

For example:

``` text
Lowest valuation
Highest valuation
Median valuation
Mean valuation
Standard deviation
Coefficient of variation
```

Display:

``` text
Valuation Dispersion: HIGH
```

High dispersion should reduce confidence and/or increase the required
margin of safety.

This is especially important when a DCF is 4× the NAV-based value.

------------------------------------------------------------------------

# 21. Data Quality Must Affect the Recommendation

This is one of the most important system changes.

Currently the system can show a strong recommendation even when multiple
required data points are unavailable.

That is dangerous.

Create:

``` text
data_quality_score = 0–100
```

Components:

-   financial statements completeness;
-   price completeness;
-   share count;
-   corporate actions;
-   dividend data;
-   revenue history;
-   earnings history;
-   debt data;
-   sector classification;
-   peer data;
-   ownership/free float;
-   latest reporting date.

Then:

``` text
if data_quality < minimum:
    recommendation = "INSUFFICIENT DATA"
```

Do not manufacture precision.

------------------------------------------------------------------------

# 22. Coverage Gates

Create explicit gates.

Example:

``` text
DATA COVERAGE
Financial statements       PASS
Market price               PASS
Shares outstanding         PASS
Revenue history            PASS
Earnings history           PASS
Debt                        PASS
Dividend history            FAIL
Peer data                   PASS
Public float                PASS/FAIL
```

Then:

``` text
Valuation Coverage: 82%
```

And:

``` text
Recommendation Confidence: LOW
```

If a required gate is missing, the recommendation should be restricted.

------------------------------------------------------------------------

# 23. Missing Data Must Never Become a Fake Number

Rules:

``` text
missing != zero
missing != negative
missing != average
missing != assumed
```

If data cannot be calculated:

``` text
DATA_UNAVAILABLE
```

and provide:

``` text
reason
source required
impact on model
```

------------------------------------------------------------------------

# 24. Historical Financial Data Engine

The system should automatically calculate the following for every
security where data exists.

## Income statement

-   revenue
-   revenue growth
-   gross profit
-   gross margin
-   EBITDA
-   EBITDA margin
-   EBIT
-   EBIT margin
-   interest expense
-   EBT
-   tax
-   net income
-   net margin
-   EPS

## Balance sheet

-   cash
-   receivables
-   inventory
-   PP&E
-   investment property
-   total assets
-   current liabilities
-   total liabilities
-   debt
-   net debt
-   equity
-   tangible equity

## Cash flow

-   CFO
-   capex
-   FCF
-   FCFF
-   FCFE
-   CFO/net income
-   FCF margin

------------------------------------------------------------------------

# 25. Automatically Calculate Trend Metrics

For every security:

``` text
1Y growth
3Y CAGR
5Y CAGR
10Y CAGR
```

where sufficient history exists.

Calculate:

-   revenue CAGR;
-   EPS CAGR;
-   EBITDA CAGR;
-   FCF CAGR;
-   book value CAGR;
-   dividend CAGR.

Also calculate:

-   volatility;
-   coefficient of variation;
-   trend direction.

------------------------------------------------------------------------

# 26. Automatically Detect Turnarounds

Create a dedicated turnaround detector.

Potential signals:

``` text
loss narrowing
margin expansion
revenue recovery
gross margin recovery
CFO improvement
debt reduction
interest expense reduction
capacity utilization improvement
working capital improvement
```

Output:

``` text
TURNAROUND STATUS

Not evident
Early
Developing
Confirmed
Failed
```

A turnaround should only be considered "confirmed" after predefined
financial evidence, not management statements alone.

------------------------------------------------------------------------

# 27. Automatically Detect Financial Distress

Create a risk engine calculating:

-   Altman Z-score where applicable;
-   interest coverage;
-   debt/equity;
-   net debt/EBITDA;
-   current ratio;
-   quick ratio;
-   CFO/debt;
-   debt maturity concentration;
-   equity erosion;
-   going-concern indicators.

Output:

``` text
Financial Risk: Low / Medium / High / Severe
```

------------------------------------------------------------------------

# 28. Sector-Aware Ratios

Do not use one scoring framework for every company.

For example:

### Banks

Use:

-   ROE
-   ROA
-   NIM
-   cost-to-income
-   NPL
-   capital adequacy
-   P/B
-   P/E

### Consumer / manufacturing

Use:

-   revenue growth
-   gross margin
-   EBITDA margin
-   ROIC
-   asset turnover
-   inventory days
-   receivable days
-   debt
-   interest coverage

### Property

Use:

-   NAV
-   occupancy
-   rental yield
-   debt
-   interest coverage
-   asset valuation

### Holding company

Use:

-   SOTP
-   NAV discount
-   investment portfolio value
-   holding-company debt

------------------------------------------------------------------------

# 29. Scoring Engine Must Be Independent From Valuation

The composite score should not be the valuation.

Keep separate:

``` text
BUSINESS QUALITY SCORE
FINANCIAL STRENGTH SCORE
GROWTH SCORE
VALUATION SCORE
MOMENTUM SCORE
RISK SCORE
DATA QUALITY SCORE
```

Then create a separate:

``` text
INVESTMENT DECISION ENGINE
```

This avoids a situation where a low-quality company receives a "Strong
Accumulate" simply because one DCF is high.

------------------------------------------------------------------------

# 30. Recommendation Logic

The final recommendation should use at least:

``` text
Valuation
Quality
Financial strength
Growth
Risk
Momentum
Data quality
Valuation confidence
```

Example rule:

``` text
High valuation upside
+
Low financial risk
+
High data confidence
=
Strong Buy
```

But:

``` text
High valuation upside
+
High financial risk
+
Low DCF confidence
=
Speculative Buy / Watch
```

And:

``` text
High apparent upside
+
insufficient data
=
Insufficient Data
```

------------------------------------------------------------------------

# 31. System-Wide Rollout Plan

This must be rolled out across the full CSE universe.

Do NOT implement only for DPL and then duplicate code.

## Phase 1 --- Audit Existing Architecture

Inventory:

-   data ingestion;
-   financial statements;
-   ratios;
-   scoring;
-   valuation;
-   scenario engine;
-   price ladder;
-   recommendation engine;
-   database/schema;
-   API endpoints;
-   UI components.

Document:

``` text
source
function
inputs
outputs
dependencies
known limitations
```

Deliverable:

`SYSTEM_AUDIT.md`

------------------------------------------------------------------------

# 32. Phase 2 --- Build Central Calculation Layer

Create reusable services/modules:

``` text
financial_metrics_engine
ratio_engine
normalization_engine
valuation_router
nav_engine
earnings_valuation_engine
dcf_engine
relative_valuation_engine
scenario_engine
buy_price_engine
sell_price_engine
risk_engine
data_quality_engine
recommendation_engine
```

No security-specific business logic.

------------------------------------------------------------------------

# 33. Phase 3 --- Build Security Classification

For every security:

``` text
primary_archetype
secondary_archetype
sector
industry
valuation_profile
risk_profile
```

The classification should be calculated from available data and allow
manual override with an audit trail.

------------------------------------------------------------------------

# 34. Phase 4 --- Run the New Engine Across ALL Securities

Do not wait for manual review one company at a time.

Run batch processing:

``` text
for security in all_cse_securities:
    ingest_data()
    calculate_financials()
    calculate_ratios()
    classify_archetype()
    route_valuation_models()
    calculate_valuations()
    calculate_scenarios()
    calculate_buy_sell_prices()
    calculate_risk()
    calculate_data_quality()
    generate_recommendation()
```

The same pipeline must process every security.

------------------------------------------------------------------------

# 35. Phase 5 --- Validation / Regression Testing

Create a test universe covering different security types:

-   profitable company;
-   loss-making company;
-   turnaround;
-   bank;
-   asset-heavy company;
-   high-growth company;
-   dividend payer;
-   holding company;
-   highly leveraged company;
-   company with incomplete data.

For each, test:

-   model routing;
-   missing data;
-   scenario ordering;
-   valuation weights;
-   buy prices;
-   sell prices;
-   recommendation;
-   confidence;
-   data quality.

------------------------------------------------------------------------

# 36. Phase 6 --- Cross-Sectional Sanity Checks

Run automated checks across the entire CSE.

Examples:

### Scenario ordering

``` text
bear <= base <= bull
```

### Weights

``` text
sum(weights) = 100%
```

### Price ladder

``` text
exceptional_buy < strong_buy < accumulate < fair < reduce < sell
```

### Margin of safety

``` text
0% <= MOS <= 100%
```

unless a clearly documented special case exists.

### Impossible outputs

Flag:

-   negative fair value where methodology cannot logically produce it;
-   DCF dramatically above all other methods;
-   zero financial strength caused by missing data;
-   valuation generated with missing critical inputs;
-   P/E on negative EPS;
-   EV/EBITDA on negative EBITDA;
-   dividend valuation without dividend history.

------------------------------------------------------------------------

# 37. Explainability Requirements

Every calculated value should be traceable.

A user should be able to click:

``` text
Fair Value: LKR XX
```

and see:

``` text
Calculation
Inputs
Source dates
Formula
Model
Weight
Confidence
```

For example:

``` text
Normalized EPS
= LKR X.XX

Applied P/E
= X.X

Earnings Value
= LKR XX.XX
```

No unexplained numbers.

------------------------------------------------------------------------

# 38. Investment Decision Card

Each security should have a standard output.

Example:

``` text
DPL.N0000

CURRENT PRICE
LKR 13.40

CENTRAL FAIR VALUE
LKR XX.XX

FAIR VALUE RANGE
LKR XX – XX

CONSERVATIVE VALUE
LKR XX

TURNAROUND VALUE
LKR XX

RECOMMENDED BUY
LKR XX – XX

ACCUMULATION RANGE
LKR XX – XX

TAKE PROFIT
LKR XX

STRONG SELL
LKR XX

VALUATION CONFIDENCE
MEDIUM

DATA QUALITY
XX/100

BUSINESS QUALITY
XX/100

FINANCIAL RISK
HIGH

TURNAROUND STATUS
DEVELOPING

DECISION
ACCUMULATE / WATCH / BUY / SELL

DECISION CONFIDENCE
XX/100
```

------------------------------------------------------------------------

# 39. "What Would Change This?" Engine

The system should calculate objective triggers.

Examples:

``` text
Upgrade if:
- revenue growth > X%
- operating margin > X%
- ROIC > WACC
- net debt/EBITDA < X
- FCF positive for X periods
```

Downgrade if:

``` text
- revenue falls > X%
- margins fall > X bps
- debt rises > X%
- equity falls > X%
- interest coverage < X
```

These thresholds should be archetype-specific.

------------------------------------------------------------------------

# 40. Price Targets Must Update Automatically

When:

-   price changes;
-   new quarterly results arrive;
-   annual report arrives;
-   debt changes;
-   shares outstanding change;
-   dividends occur;
-   sector multiples change;
-   risk-free rate changes;

the system should automatically recalculate:

``` text
fair value
buy price
sell price
margin of safety
valuation score
confidence
recommendation
```

No manual DPL-specific updates.

------------------------------------------------------------------------

# 41. Historical Versioning

Store valuation snapshots.

Example:

``` text
2026-06-30
Fair value: X
Buy price: X
Sell price: X
Confidence: X
```

Then:

``` text
2026-08-29
Fair value: Y
Buy price: Y
Sell price: Y
Confidence: Y
```

This lets the user see whether the thesis is improving or deteriorating.

------------------------------------------------------------------------

# 42. Avoid Look-Ahead Bias

For historical backtesting:

-   only use data available at the time;
-   do not use today's financial statements for past decisions;
-   respect reporting dates;
-   respect CSE publication dates;
-   use historical market prices.

This is essential if the Alpha Engine will eventually be backtested.

------------------------------------------------------------------------

# 43. Do Not Optimize the Model to One Stock

DPL must be treated as a test case, not the target.

After implementation, run the engine over the entire universe and
inspect:

-   distribution of fair values;
-   distribution of P/B;
-   distribution of P/E;
-   number of BUY signals;
-   number of SELL signals;
-   number of insufficient-data securities;
-   valuation confidence;
-   sector differences.

If 80% of the market becomes "Strong Buy", the system is broken.

If almost nothing becomes investable, the thresholds may be too strict.

------------------------------------------------------------------------

# 44. Required Final Outputs

The system should produce three levels.

## Security level

Detailed valuation and investment decision.

## Sector level

Show:

-   sector median valuation;
-   sector growth;
-   sector margins;
-   sector risk;
-   cheapest securities;
-   highest-quality securities;
-   best risk-adjusted opportunities.

## Market level

Show:

-   total CSE valuation distribution;
-   number of undervalued securities;
-   number of overvalued securities;
-   market P/E;
-   market P/B;
-   market earnings growth;
-   market risk;
-   opportunity ranking.

------------------------------------------------------------------------

# 45. Opportunity Ranking

Create a system-wide ranking:

``` text
Expected return
+
Margin of safety
+
Quality
+
Financial strength
+
Data confidence
-
Risk
-
Valuation dispersion
```

The result should be:

``` text
#1 Security
#2 Security
#3 Security
...
```

This is the key difference between a valuation calculator and an
investment engine.

------------------------------------------------------------------------

# 46. Required Engineering Principles

Claude should follow these principles throughout the implementation:

1.  **No security-specific hardcoding.**
2.  **No fake data.**
3.  **Missing data must remain missing.**
4.  **Every valuation must be explainable.**
5.  **Every recommendation must have a confidence level.**
6.  **Every model must declare whether it is appropriate.**
7.  **Scenario outputs must always be logically ordered.**
8.  **Weights must be visible.**
9.  **All calculations must be reusable across the CSE universe.**
10. **All formulas should have automated tests.**
11. **Historical calculations must avoid look-ahead bias.**
12. **A high DCF cannot automatically create a Strong Buy.**
13. **Low-quality/high-risk companies require a larger margin of
    safety.**
14. **Data quality must constrain recommendation confidence.**
15. **The system should prefer "Insufficient Data" over false
    precision.**

------------------------------------------------------------------------

# 47. DPL-Specific Validation After Implementation

Once the system-wide implementation is complete, rerun DPL.

Do not manually force the answer.

The engine should independently determine:

-   DPL archetype;
-   applicable valuation methods;
-   normalized earnings;
-   adjusted NAV;
-   DCF;
-   relative valuation;
-   bear/base/bull;
-   valuation dispersion;
-   data quality;
-   financial risk;
-   turnaround status;
-   buy price;
-   accumulation range;
-   fair value;
-   take-profit range;
-   strong-sell range;
-   recommendation.

The previous DPL output should be used as a regression test.

Specifically confirm that the following old problems no longer occur:

``` text
[ ] Bear/Base/Bull inversion
[ ] unexplained 22.70 blend
[ ] misleading 31% margin of safety
[ ] DCF dominating despite low confidence
[ ] missing data producing overconfident recommendation
[ ] "Used" valuation methods that are not actually included
[ ] missing public-float data being ignored
[ ] financial-strength score of zero without explanation
[ ] single fair value presented as precise truth
```

------------------------------------------------------------------------

# 48. Definition of Done

The upgrade is complete only when:

### Architecture

-   [ ] All valuation logic is centralized.
-   [ ] No DPL-specific valuation code exists.
-   [ ] All CSE securities can run through the same pipeline.

### Data

-   [ ] Financial data is normalized.
-   [ ] Missing data is explicitly tracked.
-   [ ] Data quality is scored.

### Valuation

-   [ ] NAV engine works.
-   [ ] Normalized earnings engine works.
-   [ ] DCF engine works.
-   [ ] Relative valuation works.
-   [ ] Model routing works.
-   [ ] Dynamic weights work.
-   [ ] Valuation confidence works.
-   [ ] Dispersion works.

### Scenarios

-   [ ] Bear \<= Base \<= Bull.
-   [ ] Scenarios are separate from valuation-method outputs.
-   [ ] Scenario assumptions are visible.

### Buy/Sell

-   [ ] Buy price is calculated.
-   [ ] Accumulation range is calculated.
-   [ ] Fair-value range is calculated.
-   [ ] Take-profit level is calculated.
-   [ ] Strong-sell level is calculated.
-   [ ] Fundamental exit conditions are calculated.

### Recommendation

-   [ ] Quality and valuation are separate.
-   [ ] Risk affects required margin of safety.
-   [ ] Data quality affects recommendation confidence.
-   [ ] Low-confidence valuation cannot automatically create Strong Buy.

### Testing

-   [ ] Cross-sectional tests pass.
-   [ ] Regression tests pass.
-   [ ] Multiple archetypes tested.
-   [ ] Historical look-ahead tests pass.

------------------------------------------------------------------------

# 49. Recommended Implementation Order

Do this in the following order and do not skip ahead:

``` text
STEP 1
Audit existing code and data model.

STEP 2
Create canonical financial-data layer.

STEP 3
Create data-quality engine.

STEP 4
Create security/archetype classification.

STEP 5
Create valuation router.

STEP 6
Implement adjusted NAV.

STEP 7
Implement normalized earnings.

STEP 8
Refactor DCF and add reverse DCF.

STEP 9
Implement relative valuation.

STEP 10
Implement confidence and dispersion.

STEP 11
Implement scenario engine.

STEP 12
Implement buy-price engine.

STEP 13
Implement sell-price / exit engine.

STEP 14
Refactor recommendation engine.

STEP 15
Run across the entire CSE universe.

STEP 16
Run regression and sanity checks.

STEP 17
Only then redesign the UI around the new outputs.
```

------------------------------------------------------------------------

# 50. Final Product Goal

The CSE Alpha Engine should ultimately answer four questions for **every
security**:

## 1. What is this company worth?

Not one number.

A defensible range:

``` text
Conservative Value
Base Value
Bull/Turnaround Value
```

## 2. How confident are we?

``` text
Data Quality
Model Confidence
Valuation Dispersion
Financial Risk
```

## 3. What price should I buy it at?

Automatically calculated:

``` text
Exceptional Buy
Strong Buy
Accumulation
```

based on the company's risk and valuation uncertainty.

## 4. At what price should I sell?

Automatically calculated:

``` text
Fair Value
Take Profit
Bull Value
Overvaluation / Strong Sell
```

with separate fundamental exit triggers.

------------------------------------------------------------------------

# 51. Key Principle

The system should NOT attempt to predict the exact future share price.

It should calculate:

> **A probability-weighted range of reasonable values, the price that
> provides sufficient margin of safety, and the conditions that would
> invalidate the investment thesis.**

That is the core objective of the upgrade.

**Build this as a reusable, security-wide valuation and decision
framework. DPL is only the validation case.**
