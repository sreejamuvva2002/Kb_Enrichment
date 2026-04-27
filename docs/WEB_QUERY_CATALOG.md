# Web Query Catalog

This document lists the exact query patterns the Phase 1 pipeline uses to discover web data.

## Search Backend

- Backend: `DuckDuckGo`
- Region: `us-en`
- Delay between DDG queries: `3` seconds
- Standard-family max results: `10`
- High-value-family max results: `20`

## Company Query Rules

Actual company queries are generated from templates in [`src/searcher.py`](/Users/sreejamuvva/Library/CloudStorage/OneDrive-UniversityofGeorgia/GNEM_Project/KB enrichment/georgia_ev_kb_builder/src/searcher.py).

Placeholders:

- `[COMPANY]` = `company_name`
- `[LOCATION]` = `location`, or `Georgia` if missing

Family assignment comes only from [`config/companies.json`](/Users/sreejamuvva/Library/CloudStorage/OneDrive-UniversityofGeorgia/GNEM_Project/KB enrichment/georgia_ev_kb_builder/config/companies.json):

- `Yes` companies use families `1,2,3,4,5,6,7,8`
- `Indirect` companies use families `1,2,3,4,6,7`
- `No` companies use families `1,3,7`

## Temporal Expansion

Temporal expansion applies only to families `3, 6, 7, 8` and to the domain-wide queries.

Temporal variants:

- `yearless`
- `2022`
- `2023`
- `2024`
- `2025`
- `2026`
- `latest`
- `recent`
- `current`

Execution rule:

- Run the `yearless` version first.
- If it returns `0` new URLs in the current run, skip the other `8` variants for that base query in that run.
- If it returns more than `0` new URLs, run the remaining `8` variants.

## Company Query Families

### Family 1: Identity

- `[COMPANY] Georgia`
- `[COMPANY] [LOCATION]`
- `[COMPANY] Georgia facility`
- `[COMPANY] Georgia operations`

### Family 2: Temporal Identity

- `[COMPANY] Georgia 2022`
- `[COMPANY] Georgia 2023`
- `[COMPANY] Georgia 2024`
- `[COMPANY] Georgia 2025`
- `[COMPANY] Georgia 2026`
- `[COMPANY] Georgia latest`
- `[COMPANY] Georgia recent`
- `[COMPANY] Georgia current`

### Family 3: Investment and Financial

Base queries:

- `[COMPANY] Georgia investment`
- `[COMPANY] Georgia jobs created`
- `[COMPANY] Georgia capital expenditure`
- `[COMPANY] Georgia expansion announcement`
- `[COMPANY] Georgia plant capacity`

Each base query can produce these 9 executed variants:

- `base query`
- `base query 2022`
- `base query 2023`
- `base query 2024`
- `base query 2025`
- `base query 2026`
- `base query latest`
- `base query recent`
- `base query current`

### Family 4: Supply Chain Relationships

- `[COMPANY] Georgia supplier`
- `[COMPANY] Georgia OEM customer`
- `[COMPANY] Georgia supply chain`
- `[COMPANY] Kia Georgia`
- `[COMPANY] Hyundai Metaplant`
- `[COMPANY] SK On`

### Family 5: EV and Battery Specific

- `[COMPANY] electric vehicle`
- `[COMPANY] EV battery`
- `[COMPANY] battery manufacturing`
- `[COMPANY] lithium ion`
- `[COMPANY] EV supply chain Georgia`

### Family 6: Documents and Regulatory

Base queries:

- `[COMPANY] Georgia press release`
- `[COMPANY] Georgia annual report`
- `[COMPANY] Georgia permit`
- `[COMPANY] Georgia SEC filing`
- `[COMPANY] Georgia PDF`
- `[COMPANY] Georgia announcement site:georgia.org`
- `[COMPANY] site:sec.gov`
- `[COMPANY] site:energy.gov`

Each base query can produce these 9 executed variants:

- `base query`
- `base query 2022`
- `base query 2023`
- `base query 2024`
- `base query 2025`
- `base query 2026`
- `base query latest`
- `base query recent`
- `base query current`

### Family 7: Economic Development

Base queries:

- `[COMPANY] Georgia economic development`
- `[COMPANY] Georgia GDEcD`
- `[COMPANY] Georgia governor announcement`
- `[COMPANY] Georgia tax incentive`

Each base query can produce these 9 executed variants:

- `base query`
- `base query 2022`
- `base query 2023`
- `base query 2024`
- `base query 2025`
- `base query 2026`
- `base query latest`
- `base query recent`
- `base query current`

### Family 8: News and Media

Base queries:

- `[COMPANY] Georgia news`
- `[COMPANY] Georgia autonews`
- `[COMPANY] Georgia Reuters`
- `[COMPANY] Georgia Bloomberg`
- `[COMPANY] Georgia manufacturing news`

Each base query can produce these 9 executed variants:

- `base query`
- `base query 2022`
- `base query 2023`
- `base query 2024`
- `base query 2025`
- `base query 2026`
- `base query latest`
- `base query recent`
- `base query current`

## Domain-Wide DDG Queries

Defined in [`config/domain_queries.json`](/Users/sreejamuvva/Library/CloudStorage/OneDrive-UniversityofGeorgia/GNEM_Project/KB enrichment/georgia_ev_kb_builder/config/domain_queries.json).

Base queries:

- `Georgia electric vehicle supply chain investment`
- `Georgia battery manufacturing plant announcement`
- `Hyundai Metaplant Bryan County tier 1 suppliers`
- `SK On Commerce Georgia battery capacity GWh`
- `Georgia EV supplier new facility groundbreaking`
- `Jackson County OR Bryan County OR Troup County electric vehicle`
- `Kia Georgia West Point supplier announcement`
- `Georgia battery recycling supply chain`
- `HMGMA suppliers announced Bryan County`
- `Georgia air permit battery manufacturing EPD`
- `DOE battery grant Georgia Ascend Elements`
- `Georgia NEVI EV charging infrastructure`
- `Rivian Georgia Normal Morgan County`
- `Georgia automotive tier 1 supplier OEM`
- `SK Battery America Commerce Georgia`
- `HMGMA Hyundai Metaplant suppliers components`
- `Georgia EV job creation announcement GDEcD`
- `selectgeorgia EV ecosystem battery manufacturer`
- `Georgia electric vehicle economic development`
- `savannahjda.com HMGMA announced suppliers`

Each domain-wide base query also uses the same 9 temporal variants and the same yearless-first rule.

## Search Portal Query Patterns

Defined in [`config/seed_urls.json`](/Users/sreejamuvva/Library/CloudStorage/OneDrive-UniversityofGeorgia/GNEM_Project/KB enrichment/georgia_ev_kb_builder/config/seed_urls.json).

For these sources, the system does not search DDG first. It generates URLs by URL-encoding `[COMPANY]` and substituting into the pattern.

### EPA ECHO

- `https://echo.epa.gov/facilities/facility-search?p_fn=[COMPANY]&p_st=GA`

### SEC EDGAR

- `https://efts.sec.gov/LATEST/search-index?q=%22[COMPANY]%22+%22Georgia%22&dateRange=custom&startdt=2020-01-01&forms=10-K,8-K`

### USAspending

- `https://api.usaspending.gov/api/v2/recipient/?keyword=[COMPANY]&page=1&limit=25`

### Georgia EPD Permit Search

- `https://permitsearch.gaepd.org/PermitSearch.aspx?name=[COMPANY]&county=&status=Active`

## Seed Discovery Pages

These are not DDG text queries, but they are direct discovery inputs used to get web data.

### Hub Seeds

- `https://www.georgia.org/press-release/`
- `https://www.selectgeorgia.com/discover-georgia/industries/EV-ecosystem-in-georgia/`
- `https://gov.georgia.gov/press-releases`
- `https://www.savannahjda.com/announced-hmgma-suppliers/`
- `https://www.kiageorgia.com/category/news/`
- `https://hmgma.com`
- `https://emobility.uga.edu/`
- `https://www.energy.gov/cmei/manufacturing/battery-manufacturing-and-recycling-grants`

### Direct Document Seeds

- `https://georgia.org/competitive-advantages/key-industries/electric-mobility`
- `https://gefa.georgia.gov`
- `https://www.gaports.com`
- `https://gisdata.georgia.gov`
- `https://afdc.energy.gov`
- `https://www.energy.gov/lpo/portfolio-projects`
- `https://www.autonews.com`
- `https://gscx.gamep.org`
- `https://patents.google.com`
- `https://www.importyeti.com`
- `https://www.marklines.com/en/supplier_db`
- `https://skon.co`
- `https://www.bryancountyga.org/economic-development`
- `https://www.georgiapower.com/business/business-solutions/growth-and-investment/economic-development/automotive-industry.html`

## Query Volume Summary

Possible company query counts before dedup, run-gap filtering, and yearless gating:

- `Yes` company: `221`
- `Indirect` company: `171`
- `No` company: `85`

Family-level maximums:

- Family `1`: `4`
- Family `2`: `8`
- Family `3`: `45`
- Family `4`: `6`
- Family `5`: `5`
- Family `6`: `72`
- Family `7`: `36`
- Family `8`: `45`

## Notes

- Actual executed queries depend on each company’s `query_families` in `companies.json`.
- Exact duplicates are removed before DDG execution.
- Queries inside their minimum run gap are skipped.
- Families `3, 6, 7, 8` and the domain-wide query set use yearless-first temporal gating.
