# georgia_ev_kb_builder

Phase 1 only. This repository discovers URLs, downloads raw documents, uploads raw files to Backblaze B2, and tracks metadata in PostgreSQL with SQLite fallback for local development.

It does not do text extraction, chunking, embedding, or RAG. Those belong in Phase 2.

## Setup

```bash
pip install -r requirements.txt
scrapling install
```

The second command installs Scrapling browser and fetcher dependencies. Run it once after `pip install` before any fetcher code runs.

Create a Backblaze B2 bucket.

Create a Backblaze B2 application key with access only to that bucket.

Create a PostgreSQL database using one of:

- Aiven Postgres free tier
- Supabase Postgres free tier
- Neon Postgres free tier
- Local PostgreSQL

Copy `.env.example` to `.env` and fill:

- `DATABASE_URL`
- `B2_BUCKET_NAME`
- `B2_ENDPOINT_URL`
- `B2_REGION`
- `B2_ACCESS_KEY_ID`
- `B2_SECRET_ACCESS_KEY`
- `TAVILY_API_KEYS` as a comma-separated list, for example `tvly-key-1,tvly-key-2`

`TAVILY_API_KEY` is also supported as a single-key fallback. When multiple keys are configured, the search client rotates through them and temporarily skips a key on Tavily auth/rate/quota errors.

Run:

```bash
python main.py --mode verify-storage
```

Then run:

```bash
python main.py --mode pilot
```

## Repository Layout

- `config/companies.json`: Generated from `GNEM_final_data.xlsx`; runtime source for dynamic company fields.
- `config/web_query_catalog.json`: Final staged web query catalog, budgets, source priorities, and dynamic templates.
- `config/seed_urls.json`: Seed hubs, documents, and search portals.
- `config/domain_queries.json`: Domain-wide discovery queries.
- `data/raw/`: Local raw document cache by content type.
- `data/metadata/`: Live metadata DB fallback path and DuckDB export path.
- `outputs/`: Excel logs and convergence reports written through a single writer queue.
- `src/`: Phase 1 pipeline modules.

## Operating Modes

- `full`: Full pipeline.
- `pilot`: Full pipeline limited to the first `pilot_companies` companies by priority.
- `seed-only`: Process seed URLs only.
- `domain-only`: Run domain-wide search only.
- `dry-run-queries --limit 5`: Print catalog-generated company and domain-wide queries without executing search/download.
- `tavily-smoke-test --query "Georgia electric vehicle supply chain"`: Run one Tavily search without downloading or storing documents.
- `single-company --company "Name"`: Run one company.
- `retry-only`: Retry retryable download failures.
- `resume`: Resume using the saved checkpoint unless `--fresh-start`.
- `convergence-check`: Read tracker metadata only and print convergence status.
- `verify-storage`: Verify Backblaze B2 access with a test object.
- `export-duckdb`: Export metadata to DuckDB for analytics only.
- `retrieve-doc --doc-id DOC_001 --target-path /tmp/file.pdf`: Retrieve a raw file from object storage without extraction.

## Design Constraints

- PostgreSQL is the primary live metadata registry.
- SQLite is fallback only when `DATABASE_URL` is not set.
- DuckDB is export-only analytics and never the live registry.
- Raw files are never stored in PostgreSQL, SQLite, or DuckDB.
- Backblaze B2 credentials are read only from environment variables.
- Upload verification uses object existence plus object size, not ETag.
- All Excel writes go through one writer thread and one queue.
- `extractor.py` is intentionally stubbed because Phase 2 is out of scope.
