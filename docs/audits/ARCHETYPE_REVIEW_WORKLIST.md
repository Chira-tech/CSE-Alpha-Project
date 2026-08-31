# Archetype review worklist — sector-model routing gap

Generated: 2026-08-31T14:20:00+00:00Z

`app.domain.archetype` deliberately refuses to auto-assign an archetype to a conglomerate-named company or one with no GICS classification on file (Appendix P2: GICS mislabels CSE holding companies — John Keells classifies as 'Capital Goods'). Those land here. Until a row gets an archetype its valuation is **PROVISIONAL**: `valuation_router` will not route it, so no maximum-conviction verdict is published — the correct, safe behaviour, not a bug. Assigning one is a human call: set `securities.archetype` and set `archetype_source` to something other than `app.domain.archetype:proposed`.

Valid archetypes: `bank`, `construction_materials`, `consumer`, `diversified_holding`, `healthcare`, `hotel`, `insurance`, `logistics`, `manufacturing`, `non_bank_finance`, `other`, `plantation`, `power_energy`, `property`, `telecom`

## Conglomerate / hotel name-gated — 25 (needs a segment-mix look)

| Ticker | Name | CSE sector |
|---|---|---|
| ASIR.N0000 | ASIRI HOSPITAL HOLDINGS PLC | Health Care Equipment & Services |
| BPPL.N0000 | B P P L HOLDINGS PLC | Household & Personal Products |
| CFVF.N0000 | FIRST CAPITAL HOLDINGS PLC | Diversified Financials |
| CIC.N0000 | C I C HOLDINGS PLC | Materials |
| CIC.X0000 | C I C HOLDINGS PLC | Materials |
| CINS.N0000 | CEYLINCO HOLDINGS PLC | Insurance |
| CINS.X0000 | CEYLINCO HOLDINGS PLC | Insurance |
| COLO.N0000 | C M HOLDINGS PLC | Retailing |
| CTHR.N0000 | C T HOLDINGS PLC | Food & Staples Retailing |
| GREG.N0000 | AMBEON HOLDINGS PLC | Consumer Durables & Apparel |
| HHL.N0000 | HEMAS HOLDINGS PLC | Capital Goods |
| HUNA.N0000 | HUNAS HOLDINGS PLC | Consumer Services |
| JAT.N0000 | JAT HOLDINGS PLC | Materials |
| JETS.N0000 | JETWING SYMPHONY PLC | Consumer Services |
| LAMB.N0000 | KOTMALE HOLDINGS PLC | Food, Beverage & Tobacco |
| LOLC.N0000 | L O L C HOLDINGS PLC | Diversified Financials |
| ONAL.N0000 | ON'ALLY HOLDINGS PLC | Real Estate Management&Development |
| PHAR.N0000 | COLOMBO CITY HOLDINGS PLC | Real Estate Management&Development |
| RFL.N0000 | RAMBODA FALLS PLC | Consumer Services |
| RHL.N0000 | RENUKA HOLDINGS PLC | Capital Goods |
| RHL.X0000 | RENUKA HOLDINGS PLC | Capital Goods |
| SERV.N0000 | THE KINGSBURY PLC | Consumer Services |
| SHL.N0000 | SOFTLOGIC HOLDINGS PLC | Capital Goods |
| SUN.N0000 | SUNSHINE HOLDINGS PLC | Food, Beverage & Tobacco |
| YORK.N0000 | YORK ARCADE HOLDINGS PLC | Real Estate Management&Development |

## No GICS classification on file — 28 (backfill the sector first)

These block upstream of archetype: `securities.cse_sector` is null, so there is nothing to propose from. Run `python -m app.cli sectors` first; several then classify automatically. The `.U0000` lines are closed-end fund units — not common equity, so they need no business archetype at all.

| Ticker | Name |
|---|---|
| AFS.N0000 | ALPHA FIRE SERVICES PLC |
| AUTO.N0000 | THE AUTODROME PLC |
| BREW.N0000 | CEYLON BEVERAGE HOLDINGS PLC |
| CALC.U0000 | CAL FIVE YEAR CLOSED END FUND (“Units”) |
| CALH.N0000 | CAPITAL ALLIANCE HOLDINGS PLC |
| CALI.U0000 | CAL FIVE YEAR OPTIMUM FUND (“Units”) |
| CALT.N0000 | CAPITAL ALLIANCE PLC |
| CALU.U0000 | CAL THREE YEAR CLOSED END FUND (“Units”) |
| COOP.N0000 | Co-operative Insurance Company PLC |
| CSLK.N0000 | CABLE SOLUTIONS PLC |
| EML.N0000 | E M L CONSULTANTS PLC |
| EXT.N0000 | EXTERMINATORS PLC |
| FCT.N0000 | First Capital Treasuries PLC |
| HBS.N0000 | hSenid Business Solutions PLC |
| INME.N0000 | INSUREME INSURANCE BROKERS PLC |
| JFP.N0000 | JF PACKAGING PLC |
| JXG.N0000 | JANASHAKTHI LIMITED |
| KPHL.N0000 | KAPRUKA HOLDINGS PLC |
| LCBF.N0000 | LANKA CREDIT AND BUSINESS FINANCE PLC |
| LGIL.N0000 | LOLC GENERAL INSURANCE PLC |
| LUMX.N0000 | LUMINEX PLC |
| MDL.N0000 | MYLAND DEVELOPMENTS PLC |
| PACK.N0000 | Ex-pack Corrugated Cartons PLC |
| PKME.N0000 | DIGITAL MOBILITY SOLUTIONS LANKA PLC |
| SDF.N0000 | SARVODAYA DEVELOPMENT FINANCE PLC |
| SLND.N0000 | SERENDIB LAND PLC |
| SWAD.N0000 | SWADESHI INDUSTRIAL WORKS  PLC |
| UBF.N0000 | UB FINANCE PLC |
