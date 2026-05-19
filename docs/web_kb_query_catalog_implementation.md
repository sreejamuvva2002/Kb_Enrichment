# Web KB Query Catalog Implementation

## What changed

- Added a config-driven final web query catalog in `config/web_query_catalog.json`.
- Replaced the old broad Python query families with staged catalog generation.
- Added dynamic placeholder expansion from company/config fields with safe missing-field skips.
- Added company alias support through optional `company_aliases`, `aliases`, or `known_aliases`.
- Added query budgets by EV relevance: Yes, Indirect, No, Unknown.
- Added family-aware URL pre-filtering before download.
- Added web document metadata tables while keeping the existing URL registry.
- Updated Backblaze object keys to include file type, stable company identifier, document id, and content hash prefix.
- Added dry-run query generation and lightweight tests.

## Catalog location

Query templates, budgets, temporal rules, source-priority domains, source vocabularies, and domain-wide templates live in:

`config/web_query_catalog.json`

The code reads this file at runtime through `src/query_catalog.py`.

## How the catalog is used

Company query generation:

- Stage 1 core evidence queries run for every company when required placeholders exist.
- Stage 2 gap-filling families run only when simple field/importance triggers indicate they are needed.
- Stage 3 structured portal lookups continue to come from `config/seed_urls.json`.
- Stage 4 domain-wide discovery uses `domain_wide_templates` and OEM anchors derived dynamically from company `primary_oems`.
- Stage 5/latest-style queries run only when `--include-fresh` is passed.

Missing fields are skipped per template. Empty strings are not inserted into queries.

## Dynamic fields

Supported placeholders include:

- `COMPANY`
- `COMPANY_ID`
- `COMPANY_ALIAS`
- `CITY`
- `COUNTY`
- `STATE`
- `ADDRESS`
- `ADDRESS_FRAGMENT`
- `PRODUCT_SERVICE`
- `EV_ROLE`
- `FACILITY_TYPE`
- `INDUSTRY_GROUP`
- `PRIMARY_OEM`
- `SUPPLIER_TYPE`
- `CATEGORY`
- `TRUSTED_DOMAIN`
- `TRUSTED_NEWS_OR_TRADE_DOMAIN`
- `OEM_ANCHOR`

Current `config/companies.json` does not include stable `company_id` or aliases, but the code will use them when available.

## How to run

Dry-run company and domain-wide query generation:

```bash
python main.py --mode dry-run-queries --limit 5
```

Include freshness/latest query families:

```bash
python main.py --mode dry-run-queries --limit 5 --include-fresh
```

Run company-level discovery/download/archive for a small test set:

```bash
python main.py --mode pilot --pilot-count 5
```

Run one company:

```bash
python main.py --mode single-company --company "Company Name"
```

Run domain-wide discovery:

```bash
python main.py --mode domain-only
```

Run a Tavily smoke test without downloading or storing documents:

```bash
python main.py --mode tavily-smoke-test --query "\"Georgia\" electric vehicle supply chain investment"
```

Verify Backblaze B2:

```bash
python main.py --mode verify-storage
```

## Tavily keys

Put Tavily keys in your local `.env` file:

```bash
TAVILY_API_KEYS=tvly-key-1,tvly-key-2,tvly-key-3
```

The code reads `TAVILY_API_KEYS` first and rotates through the comma-separated list. `TAVILY_API_KEY` is supported as a single-key fallback. Keys are temporarily skipped when Tavily returns auth, rate-limit, or quota status codes.

## Metadata stored

The existing `urls` table remains the discovered URL registry. It now also tracks additional source metadata such as:

- `company_id`
- `canonical_url`
- `query_family`
- `query_stage`
- `source_type`
- `source_priority`
- `retrieved_at`
- `published_date`
- `processing_status`
- `confidence_score`
- `rejection_reason`

New tables separate archived web evidence from URL discovery:

- `web_documents`: accepted/downloaded document metadata and B2 location.
- `web_document_company_links`: stable company-document links when company identifiers exist.

Raw files remain outside PostgreSQL and are archived to Backblaze B2 when storage is enabled.

## Filtering and dedupe

Before download, search results are checked for:

- blocklist match
- minimum relevance score
- company/entity match
- geography match for facility, investment, permit, government/economic-development, and news families
- product/industry signal when required
- EV/battery signal when required
- OEM relationship signal when required

Existing exact dedupe remains:

- normalized URL dedupe through `normalized_url`
- content hash dedupe through `content_fingerprints`
- B2 object path uses content hash prefix

Near-duplicate and syndicated-news clustering are represented as future design work; exact content hash and canonical/final URL fields are now in place.

## Not implemented yet

This task intentionally does not implement:

- text extraction
- chunking
- embeddings
- pgvector retrieval
- fact extraction
- final RAG retrieval
- conflict resolution workflows
- full near-duplicate detection
- Tavily API execution
