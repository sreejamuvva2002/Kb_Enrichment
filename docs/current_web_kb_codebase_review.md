# Current Web KB Codebase Review

## 1. Current project overview

This repo is a Phase 1 web-enrichment pipeline for a Georgia EV supply-chain KB. It discovers URLs, downloads raw web files, optionally uploads them to Backblaze B2, and records URL/file/run metadata in PostgreSQL with SQLite fallback.

It does not currently implement text extraction, chunking, embeddings, pgvector storage, fact extraction, or RAG retrieval. `README.md` and `src/extractor.py` explicitly treat those as Phase 2.

Relevant areas:

- Excel KB ingestion: not implemented in this repo. `config/companies.json` is described as generated from `GNEM_final_data.xlsx` and is used as the company/config input.
- Web enrichment: implemented through DuckDuckGo search, seed URL downloading, search-portal URL generation, hub-link extraction, relevance scoring, blocklist filtering, downloading, B2 upload, and metadata tracking.
- PostgreSQL storage: implemented for web URL/file metadata and query/run tracking only.
- Retrieval: only raw-object retrieval from B2 by `doc_id` or `object_key`; no semantic or keyword RAG retrieval.

## 2. Current folder/file map

- `main.py`: CLI entry point and pipeline orchestrator. Handles modes, checkpoints, seed/domain/company search, downloads, retries, B2 verification, DuckDB export, and raw document retrieval.
- `src/searcher.py`: DuckDuckGo search, query-template expansion, temporal variants, company/domain query collection, search-portal URL generation, relevance scoring, priority-domain checks, blocklist checks.
- `src/downloader.py`: Downloads URLs using `httpx` for binary candidates and Scrapling for pages/dynamic fallback. Detects file type, hashes content, writes local raw files, uploads to B2, marks metadata.
- `src/tracker.py`: Metadata registry service over SQLAlchemy models. Normalizes URLs, deduplicates URLs/content hashes, records download/upload metadata, query convergence, query performance, run history, and URL-company mappings.
- `src/db.py`: SQLAlchemy schema and DB connection setup. Defines live metadata tables: `urls`, `url_company_map`, `query_convergence`, `query_performance`, `company_convergence`, `content_fingerprints`, `runs`.
- `src/storage.py`: S3-compatible Backblaze B2 client wrapper. Builds object keys, uploads/downloads files, verifies objects, generates presigned URLs, performs healthcheck roundtrip.
- `src/link_extractor.py`: Extracts links from downloaded hub HTML, filters links by blocklist and relevance score, queues new URLs.
- `src/framework_updater.py`: Writes Excel output logs/reports in `outputs/`: download log, document registry, processing log, convergence summary/report, run history.
- `src/extractor.py`: Stub only. All extraction functions raise `NotImplementedError`.
- `src/__init__.py`: Shared repo paths and timestamp/YAML helpers.
- `config/companies.json`: 205-company dynamic input generated from Excel. Contains company attributes and `query_families`; used for query generation.
- `config/seed_urls.json`: Direct seed documents, hub pages, and search-portal patterns.
- `config/domain_queries.json`: Domain-wide discovery query bases.
- `config/blocklist.json`: Noisy/social/job/directory domains and URL fragments to skip.
- `config/settings.yaml`: DDG settings, rate limits, concurrency, size limits, retry limits, relevance threshold, convergence/gap settings.
- `config/storage.yaml`: B2/S3-compatible storage settings, env var names, object-key pattern, retention policy.
- `config/database.yaml`: PostgreSQL env var, SQLite fallback path, DuckDB export path, migration behavior.
- `docs/WEB_QUERY_CATALOG.md`: Human-readable query catalog documenting the current query rules.
- `docs/EXACT_WEB_QUERIES.md`: Large generated query listing; documentation/output, not runtime logic.
- `data/raw/*`: Local raw document cache by file type.
- `data/metadata/*`: SQLite fallback and DuckDB export location.
- `outputs/*`: Runtime Excel logs/reports; currently only `.gitkeep` is committed.

## 3. Current Excel KB pipeline

The structured Excel KB parent-child ingestion is not visible in this codebase. There is no code here that reads the source Excel workbook, normalizes structured company rows into parent/child chunks, embeds chunks, or stores those chunks in PostgreSQL.

Visible Excel-related behavior:

- `config/companies.json` is the runtime company list and is described as generated from `GNEM_final_data.xlsx`.
- The pipeline reads `companies.json` with `load_companies()` and sorts by `priority` and `company_name`.
- Company values used for web search include `company_name`, `location`, `query_families`, and other metadata fields, but no normalized `company_id` is present.
- `src/framework_updater.py` writes operational Excel logs and reports. These are not the structured KB ingestion pipeline.

Visible parent/child chunking:

- No parent chunk creation code is present.
- No child chunk creation code is present.
- No chunk tables, embedding tables, or pgvector logic are present.

## 4. Current web search / crawler pipeline

Implemented:

- DuckDuckGo text search through `ddgs`.
- Direct seed URL downloading.
- Hub-page crawling at depth 1 by extracting links from downloaded HTML.
- Search-portal URL generation from configured patterns.
- Domain-wide discovery queries.
- Query convergence tracking to avoid unnecessary reruns.

Not implemented:

- Tavily integration.
- General recursive crawler.
- Robots/sitemap crawling.
- Clean text extraction after download.

Query generation:

- Company queries are generated from templates in `src/searcher.py`.
- `[COMPANY]` and `[LOCATION]` are filled from `config/companies.json`.
- Each company chooses query families dynamically from `query_families`.
- Some families expand into temporal variants: yearless plus configured year/currentness suffixes.
- Domain-wide queries come from `config/domain_queries.json`.
- Search-portal URLs come from `config/seed_urls.json` patterns and URL-encoded company names.

Noise filtering:

- `config/blocklist.json` filters known noisy domains/fragments.
- `score_url_relevance()` applies keyword/domain scoring.
- URLs below `relevance_min_score` are recorded but not downloaded.
- Hub-extracted links are filtered by blocklist and relevance score.

Concern: several search templates, relevance keywords, priority domains, and domain-wide query strings are hardcoded or static config/doc values rather than derived from normalized KB tables.

## 5. Current storage design

PostgreSQL/SQLite stores web metadata, not raw file bytes.

Current tables visible in `src/db.py`:

- `urls`: URL registry, discovery metadata, download status, file metadata, B2 location, relevance/filter fields.
- `url_company_map`: many-to-many-ish URL-to-company name mapping.
- `content_fingerprints`: SHA-256 content hash registry for exact duplicate detection.
- `query_convergence`: query run/convergence tracking.
- `query_performance`: query yield/relevance tracking.
- `company_convergence`: company-level convergence summary.
- `runs`: pipeline run history.

Raw documents:

- Downloaded locally under `data/raw/{html,pdf,json,csv,xlsx,docx}` when retained.
- Uploaded to Backblaze B2 when `upload_after_download` is enabled.
- B2 metadata is stored on `urls` as `bucket_name`, `object_key`, `cloud_uri`, upload status/timestamps/etag/version/size.

Not stored now:

- Clean extracted text.
- Chunks.
- Embeddings/vectors.
- Extracted facts/evidence.
- Web document entities linked by stable normalized company IDs.

Missing future tables:

- `web_documents` or equivalent raw document metadata table separate from URL discovery.
- `web_document_versions` or content snapshot table if recrawls are expected.
- `web_document_company_links` using stable `company_id`.
- `web_extracted_text`.
- `web_chunks` with parent/child structure and source offsets.
- `web_embeddings` or pgvector columns.
- `web_facts` / `web_evidence`.
- `processing_jobs` or document-stage status table beyond the current URL fields.

## 6. Current metadata design

Present or partially present:

- `source_url`: present as `url`; B2 object metadata also includes `source_url`.
- `canonical_url`: not present. `normalized_url` exists for dedupe; `final_url` records redirects.
- `company_id`: missing. Only `company_name` / `discovered_for_company` / `url_company_map.company_name`.
- `query_used`: present as `discovered_by_query`.
- `query_family`: present in query tracking tables, not on each URL row.
- `source_type`: partial via `url_type`, `source_backend`, file extension/content type.
- `source_priority`: partial via `priority_domain`, seed priority is not persisted on `urls`.
- `retrieved_at`: partial via `last_download_at`, `uploaded_at`, Excel `Date_Acquired`.
- `published_date`: missing.
- `content_hash`: present as `content_fingerprint` SHA-256.
- `backblaze_path`: present as `object_key` / `cloud_uri`.
- `processing_status`: partial via `last_download_status`, `is_extracted`, Excel processing log.
- `evidence_type`: missing.
- `confidence_score`: missing.

Additional current metadata:

- URL normalization, domain, first/last discovery timestamps, DDG title/snippet, HTTP status, redirects, response time, content type, file path/size, ETag, last modified, duplicate flags, upload verification fields, run/query convergence stats.

## 7. Current filtering/deduplication

Current rules:

- URL deduplication by `normalized_url` unique constraint.
- URL normalization lowercases scheme/netloc, strips default ports/fragments, sorts query parameters, and normalizes empty paths.
- Content exact deduplication by SHA-256 in `content_fingerprints`.
- Blocklist filtering through `config/blocklist.json`.
- Relevance filtering through `score_url_relevance()` and `relevance_min_score`.
- Download validation rejects unknown content type, empty file, oversized file, 403/404, JS-required placeholder pages, timeouts, connection errors, and redirect loops.
- Retry logic exists for timeout/connection/JS-required failures.

Missing:

- Near-duplicate detection.
- Canonical URL resolution beyond redirect final URL.
- Strong geography validation against company/facility locations.
- Strong company/entity validation.
- Persistent per-document query family on the URL/document row.
- Rich noisy-document classification beyond blocklist and keyword score.

## 8. Current retrieval design

The only retrieval-like feature is `main.py --mode retrieve-doc`, which downloads a raw object from B2 to a target path using `doc_id` or `object_key`.

There is no RAG retrieval in this repo:

- No parent/child chunk retrieval.
- No BM25.
- No vector search or pgvector.
- No metadata-filtered semantic retrieval.
- No reranking.
- No hybrid retrieval.
- Web data is not included in any RAG retrieval path because extraction/chunking/embedding are not implemented here.

## 9. Gaps against the target future pipeline

Target step coverage:

- Web search / crawler / Tavily: partially present with DuckDuckGo, seeds, portals, and shallow hub link extraction; Tavily and robust crawling are missing.
- Download document/page/PDF: present for HTML, PDF, JSON, CSV, XLSX, DOCX.
- Store raw file in Backblaze B2: present and configurable.
- Store file metadata in PostgreSQL: present for URL-centric metadata.
- Later extract clean text + metadata + facts: missing; extractor is stubbed.
- Store chunks/vectors/facts in PostgreSQL/pgvector: missing.

Real missing pieces:

- Stable web document model separate from search URL rows.
- Stable link from web documents to normalized structured KB company IDs.
- Canonical URL and document-version handling.
- Text extraction pipeline by file type.
- Clean-text storage and extraction status transitions.
- Parent/child web chunking.
- Embedding generation and pgvector schema.
- Fact/evidence extraction schema.
- Retrieval integration combining structured KB chunks and web evidence.
- Tavily/crawler abstraction if multiple discovery backends are required.

## 10. Risks / concerns

- Current relevance scoring and query templates include hardcoded domain/keyword assumptions.
- No stable `company_id` means web evidence can only link by company name.
- URL registry and document metadata are coupled in one `urls` table.
- Source traceability is partial: query text exists, but query family and source priority are not persisted per document.
- No canonical URL, published date, evidence type, confidence score, or source-quality model.
- No extracted fact/evidence table.
- No web chunk/vector storage.
- Exact hash dedupe exists, but near-duplicates and content updates are not handled.
- No strong entity/geography validation before web data becomes evidence.
- Structured Excel KB and web evidence KB are not clearly connected in this repo.

## 11. Recommended next implementation steps

1. Define the web KB PostgreSQL schema: `web_documents`, document versions/snapshots, `web_document_company_links` with `company_id`, extraction jobs/status, chunks, embeddings, and facts/evidence.
2. Add a stable company lookup layer from the normalized structured KB/PostgreSQL, replacing company-name-only linking and avoiding hardcoded KB values.
3. Split URL discovery metadata from document metadata so search results, redirects, duplicates, and stored raw documents are modeled cleanly.
4. Persist missing document metadata: canonical URL, query family, source type/priority, retrieved timestamp, published date, content hash, B2 object path, processing status.
5. Implement extraction as a separate Phase 2 pipeline that reads raw files from B2/local cache, writes clean text and metadata, and tracks failures.
6. Implement dynamic parent/child chunking and pgvector embedding storage for web documents.
7. Add fact/evidence extraction with source offsets, confidence, evidence type, and links back to raw document/chunk/company.
8. Add stronger dedupe and validation before retrieval: canonicalization, near-duplicate checks, company/entity matching, and Georgia/location validation.
9. Integrate retrieval only after web chunks/facts are stored, keeping structured KB retrieval and web evidence retrieval traceable but joinable.
