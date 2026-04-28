from __future__ import annotations

import argparse
import json
import logging
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from src import CHECKPOINT_DIR, CONFIG_DIR, REPO_ROOT, iso_now, load_yaml
from src.downloader import Downloader
from src.framework_updater import (
    enqueue_convergence_report,
    enqueue_convergence_update,
    enqueue_download_row,
    enqueue_processing_log,
    enqueue_registry_row,
    enqueue_run_summary,
    start_writer_thread,
    stop_writer_thread,
)
from src.link_extractor import process_hub_page
from src.searcher import (
    collect_domain_wide,
    collect_for_company,
    generate_search_portal_url_records,
    load_companies,
    load_seed_urls,
)
from src.storage import StorageManager
from src.tracker import DOMAIN_WIDE_COMPANY, Tracker

LOGGER = logging.getLogger(__name__)
CHECKPOINT_PATH = CHECKPOINT_DIR / "pipeline_checkpoint.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Georgia EV KB Builder Phase 1 pipeline")
    parser.add_argument(
        "--mode",
        required=True,
        choices=[
            "full",
            "pilot",
            "seed-only",
            "retry-only",
            "domain-only",
            "resume",
            "single-company",
            "convergence-check",
            "verify-storage",
            "export-duckdb",
            "retrieve-doc",
        ],
    )
    parser.add_argument("--company", help="Company name for single-company mode.")
    parser.add_argument("--pilot-count", type=int, help="Override the configured pilot company count.")
    parser.add_argument("--run-id", help="Explicit run identifier.")
    parser.add_argument("--fresh-start", action="store_true", help="Ignore any existing checkpoint.")
    parser.add_argument("--doc-id", help="Document ID for retrieve-doc mode.")
    parser.add_argument("--object-key", help="Object key for retrieve-doc mode.")
    parser.add_argument("--target-path", help="Target path for retrieve-doc mode.")
    return parser.parse_args()


def chunked(items: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def checkpoint_payload(run_id: str, processed_companies: list[str]) -> dict[str, Any]:
    return {"run_id": run_id, "processed_companies": processed_companies, "saved_at": iso_now()}


def save_checkpoint(run_id: str, processed_companies: list[str]) -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint_payload(run_id, processed_companies), indent=2), encoding="utf-8")


def load_checkpoint() -> dict[str, Any] | None:
    if not CHECKPOINT_PATH.exists():
        return None
    return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))


def clear_checkpoint() -> None:
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()


def enrich_result(result: dict[str, Any], tracker: Tracker, run_id: str, context: dict[str, Any]) -> dict[str, Any]:
    record = tracker.get_url_record(result["url"]) or {}
    enriched = dict(result)
    enriched["relevance_score"] = record.get("relevance_score")
    enriched["priority_domain"] = record.get("priority_domain")
    enriched["ddg_title"] = record.get("ddg_title")
    enriched["ddg_snippet"] = record.get("ddg_snippet")
    enriched["run_id"] = run_id
    for key in ("source_name", "category", "sub_category", "url_type"):
        if context.get(key) is not None:
            enriched[key] = context.get(key)
    return enriched


def queue_excel_outputs(result: dict[str, Any]) -> None:
    enqueue_download_row(result)
    enqueue_registry_row(result)
    enqueue_processing_log(
        {
            "doc_id": result.get("doc_id"),
            "document_name": result.get("doc_id"),
            "stage_id": "phase1_download",
            "stage_name": "Phase 1 Download",
            "status": result.get("download_status"),
            "records_processed": 1,
            "notes": result.get("notes"),
        }
    )


def drain_queue(url_queue: queue.Queue) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while not url_queue.empty():
        items.append(url_queue.get())
    return items


def download_entries(
    entries: list[dict[str, Any]],
    downloader: Downloader,
    tracker: Tracker,
    run_id: str,
    settings: dict[str, Any],
    hub_queue: queue.Queue | None = None,
) -> dict[str, int]:
    stats = {"downloaded_ok": 0, "failed": 0, "duplicates_skipped": 0}
    if not entries:
        return stats
    batch_size = int(settings["download_batch_size"])
    max_workers = int(settings["max_concurrent_downloads"])
    for batch in chunked(entries, batch_size):
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(downloader.download_url, item["url"], item.get("company_name"), item.get("doc_id")): item
                for item in batch
            }
            for future in as_completed(future_map):
                item = future_map[future]
                result = future.result()
                enriched = enrich_result(result, tracker, run_id, item)
                queue_excel_outputs(enriched)
                if enriched["download_status"] == "Downloaded" and enriched["downloaded"] == "Yes":
                    stats["downloaded_ok"] += 1
                elif enriched["download_status"] == "Duplicate Content":
                    stats["duplicates_skipped"] += 1
                elif enriched["download_status"] not in {"Already Exists", "Skipped - Blocked Domain", "Skipped - Low Relevance"}:
                    stats["failed"] += 1
                if (
                    hub_queue is not None
                    and item.get("url_type") == "hub"
                    and enriched.get("download_status") == "Downloaded"
                    and enriched.get("file_type") == "html"
                    and enriched.get("file_path")
                ):
                    process_hub_page(
                        Path(enriched["file_path"]),
                        item["url"],
                        item.get("company_name") or item.get("source_name") or "Seed Hub",
                        tracker,
                        hub_queue,
                    )
    return stats


def prepare_seed_entries(tracker: Tracker, companies: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seed_urls = load_seed_urls()
    downloadable: list[dict[str, Any]] = []
    search_portal_entries: list[dict[str, Any]] = []
    for seed in seed_urls:
        if seed.get("enabled", True) is False:
            LOGGER.info("Skipping disabled seed entry: %s", seed["source_name"])
            continue
        if seed["url_type"] == "search_portal":
            for record in generate_search_portal_url_records(seed, companies):
                tracker.add_url(
                    record["url"],
                    seed["url"],
                    record["company_name"],
                    None,
                    None,
                    priority_domain=True,
                    url_type="search_portal",
                    source_backend="seed_search_portal",
                    notes=f"Generated from {seed['source_name']}",
                )
                tracker.add_url_company_mapping(record["url"], record["company_name"], seed["url"])
                if not tracker.is_seed_url_within_gap(record["url"]):
                    search_portal_entries.append(
                        {
                            "url": record["url"],
                            "company_name": record["company_name"],
                            "source_name": seed["source_name"],
                            "category": seed["category"],
                            "sub_category": seed["sub_category"],
                            "url_type": "search_portal",
                        }
                    )
            continue
        tracker.add_url(
            seed["url"],
            seed["url"],
            seed["source_name"],
            None,
            None,
            priority_domain=True,
            url_type=seed["url_type"],
            source_backend="seed",
            notes=seed["description"],
        )
        if tracker.is_seed_url_within_gap(seed["url"]):
            continue
        downloadable.append(
            {
                "url": seed["url"],
                "company_name": seed["source_name"],
                "source_name": seed["source_name"],
                "category": seed["category"],
                "sub_category": seed["sub_category"],
                "url_type": seed["url_type"],
            }
        )
    return downloadable, search_portal_entries


def selected_companies(mode: str, args: argparse.Namespace, settings: dict[str, Any]) -> list[dict[str, Any]]:
    companies = load_companies()
    if mode == "pilot":
        pilot_count = args.pilot_count or int(settings["pilot_companies"])
        return companies[: pilot_count]
    if mode == "single-company":
        if not args.company:
            raise ValueError("--company is required for single-company mode.")
        filtered = [row for row in companies if row["company_name"].lower() == args.company.lower()]
        if not filtered:
            raise ValueError(f"Company not found: {args.company}")
        return filtered
    return companies


def validate_storage_if_enabled(storage: StorageManager, storage_config: dict[str, Any]) -> None:
    if not storage_config.get("upload_after_download", True):
        return
    client = storage.get_storage_client()
    client.head_bucket(Bucket=storage.bucket_name())


def run_pipeline(args: argparse.Namespace) -> None:
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    storage_config = load_yaml(CONFIG_DIR / "storage.yaml")
    tracker = Tracker()
    downloader = Downloader(tracker)
    storage = StorageManager(storage_config)
    start_writer_thread()
    started_at = time.time()
    run_id = args.run_id or f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    if args.fresh_start:
        clear_checkpoint()
    checkpoint = None if args.fresh_start else load_checkpoint()
    processed_companies = list(checkpoint.get("processed_companies", [])) if checkpoint else []
    hub_queue: queue.Queue = queue.Queue()
    stats = {
        "total_urls_seen": tracker.count_urls(),
        "new_urls_found": 0,
        "already_known": 0,
        "downloaded_ok": 0,
        "failed": 0,
        "duplicates_skipped": 0,
    }
    try:
        validate_storage_if_enabled(storage, storage_config)
        companies = selected_companies("full" if args.mode == "resume" else args.mode, args, settings)
        seed_entries, search_portal_entries = prepare_seed_entries(tracker, companies)

        if args.mode in {"full", "pilot", "resume", "seed-only", "single-company"}:
            seed_stats = download_entries(seed_entries, downloader, tracker, run_id, settings, hub_queue)
            for key in seed_stats:
                stats[key] += seed_stats[key]
            hub_discovered = drain_queue(hub_queue)
            hub_stats = download_entries(hub_discovered, downloader, tracker, run_id, settings)
            for key in hub_stats:
                stats[key] += hub_stats[key]

        if args.mode in {"full", "pilot", "resume", "domain-only", "single-company"}:
            domain_stats = collect_domain_wide(tracker, run_id)
            domain_entries = [{"url": url, "company_name": DOMAIN_WIDE_COMPANY, "url_type": "document"} for url in domain_stats["discovered_urls"]]
            stats["new_urls_found"] += len(domain_entries)
            download_stats = download_entries(domain_entries, downloader, tracker, run_id, settings)
            for key in download_stats:
                stats[key] += download_stats[key]

        if args.mode in {"full", "pilot", "resume", "single-company"}:
            for index, company in enumerate(companies, start=1):
                if company["company_name"] in processed_companies:
                    continue
                try:
                    projected_bundle_hash = None
                    bundle_preview = __import__("src.searcher", fromlist=["build_query_bundle"]).build_query_bundle(company)
                    if bundle_preview:
                        projected_bundle_hash = tracker.compute_query_set_hash(
                            bundle_preview,
                            {
                                "temporal_families": [3, 6, 7, 8],
                                "variants": ["yearless", "2022", "2023", "2024", "2025", "2026", "latest", "recent", "current"],
                                "yearless_first": True,
                            },
                        )
                    company_convergence = tracker.get_company_convergence_record(company["company_name"])
                    if company_convergence and company_convergence["all_converged"] and company_convergence["query_set_hash"] == projected_bundle_hash:
                        LOGGER.info("Skipping converged company: %s", company["company_name"])
                        processed_companies.append(company["company_name"])
                        continue
                    collected = collect_for_company(company, tracker, run_id)
                    discovered_entries = [
                        {"url": url, "company_name": company["company_name"], "url_type": "document"}
                        for url in collected["discovered_urls"]
                    ]
                    stats["new_urls_found"] += len(discovered_entries)
                    company_download_stats = download_entries(discovered_entries, downloader, tracker, run_id, settings)
                    for key in company_download_stats:
                        stats[key] += company_download_stats[key]
                except Exception as exc:
                    LOGGER.exception("Company failed: %s", company["company_name"])
                    enqueue_processing_log(
                        {
                            "doc_id": None,
                            "document_name": company["company_name"],
                            "stage_id": "company_run",
                            "stage_name": "Company Pipeline",
                            "status": "Failed",
                            "records_processed": 0,
                            "error_message": str(exc),
                            "notes": "Company failure was isolated and the run continued.",
                        }
                    )
                finally:
                    processed_companies.append(company["company_name"])
                    if index % int(settings["checkpoint_every_n_companies"]) == 0:
                        save_checkpoint(run_id, processed_companies)

        if args.mode in {"full", "pilot", "resume", "seed-only", "single-company"}:
            portal_stats = download_entries(search_portal_entries, downloader, tracker, run_id, settings)
            for key in portal_stats:
                stats[key] += portal_stats[key]

        if args.mode in {"full", "pilot", "resume", "retry-only", "single-company"}:
            retry_stats = downloader.retry_failed()
            for result in retry_stats["results"]:
                enriched = enrich_result(result, tracker, run_id, {"url_type": "document"})
                queue_excel_outputs(enriched)
                if enriched["download_status"] == "Downloaded" and enriched["downloaded"] == "Yes":
                    stats["downloaded_ok"] += 1
                elif enriched["download_status"] == "Duplicate Content":
                    stats["duplicates_skipped"] += 1
                elif enriched["download_status"] != "Already Exists":
                    stats["failed"] += 1

        convergence_summary = tracker.get_convergence_summary()
        enqueue_convergence_update(convergence_summary["companies"])
        overall_pct = tracker.get_overall_convergence_pct()
        re_run_recommended = overall_pct < 95.0
        project_summary = {
            "Overall Convergence Pct": overall_pct,
            "Converged Companies": len(convergence_summary["converged_companies"]),
            "Unconverged Companies": len(convergence_summary["unconverged_companies"]),
            "Low Yield Queries": len(convergence_summary["low_yield_queries"]),
            "Re-run Recommended": "Yes" if re_run_recommended else "No",
        }
        enqueue_convergence_report(
            {
                "company_rows": [
                    {
                        "Company_Name": row["company_name"],
                        "Total_Queries": row["total_queries"],
                        "Converged_Queries": row["converged_queries"],
                        "Query_Set_Hash": row["query_set_hash"],
                        "All_Converged": row["all_converged"],
                        "Last_Updated": row["last_updated"],
                    }
                    for row in convergence_summary["companies"]
                ],
                "low_yield_rows": convergence_summary["low_yield_queries"],
                "project_summary": project_summary,
            }
        )
        completed_at = iso_now()
        duration_minutes = round((time.time() - started_at) / 60.0, 2)
        run_summary = {
            "run_id": run_id,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)),
            "completed_at": completed_at,
            "total_urls_seen": tracker.count_urls(),
            "new_urls_found": stats["new_urls_found"],
            "already_known": stats["already_known"],
            "downloaded_ok": stats["downloaded_ok"],
            "failed": stats["failed"],
            "duplicates_skipped": stats["duplicates_skipped"],
            "project_convergence_pct": overall_pct,
            "duration_minutes": duration_minutes,
            "notes": "Re-run recommended" if re_run_recommended else "No re-run needed yet",
        }
        tracker.save_run_summary(run_summary)
        enqueue_run_summary(run_summary)
        save_checkpoint(run_id, processed_companies)
        print(f"Run ID: {run_id}")
        print(f"Total URLs in registry: {tracker.count_urls()}")
        print(f"Downloaded OK: {stats['downloaded_ok']}")
        print(f"Duplicate content skipped: {stats['duplicates_skipped']}")
        print(f"Failed downloads: {stats['failed']}")
        print(f"Project convergence %: {overall_pct}")
        print(f"Re-run recommended: {'Yes' if re_run_recommended else 'No'}")
        print(f"Run duration (minutes): {duration_minutes}")
    finally:
        stop_writer_thread()
        tracker.close()


def run_convergence_check() -> None:
    tracker = Tracker()
    try:
        summary = tracker.get_convergence_summary()
        print(f"Overall convergence %: {summary['overall_pct']}")
        for row in summary["companies"]:
            print(
                f"{row['company_name']}: {row['converged_queries']}/{row['total_queries']} converged | "
                f"all_converged={row['all_converged']}"
            )
    finally:
        tracker.close()


def run_verify_storage() -> None:
    storage = StorageManager()
    result = storage.verify_storage_roundtrip()
    print("Storage verification:", "success" if result["verified"] else "failed")


def run_export_duckdb() -> None:
    tracker = Tracker()
    try:
        output = tracker.export_metadata_to_duckdb()
        print(f"DuckDB export written to: {output}")
    finally:
        tracker.close()


def run_retrieve_doc(args: argparse.Namespace) -> None:
    if not args.target_path:
        raise ValueError("--target-path is required for retrieve-doc mode.")
    tracker = Tracker()
    storage = StorageManager()
    try:
        object_key = args.object_key
        if not object_key:
            if not args.doc_id:
                raise ValueError("Provide --doc-id or --object-key for retrieve-doc mode.")
            record = tracker.get_by_doc_id(args.doc_id)
            if not record or not record.get("object_key"):
                raise ValueError(f"No object key found for doc_id={args.doc_id}")
            object_key = record["object_key"]
        target = storage.download_object(object_key, args.target_path)
        print(f"Retrieved document to: {target}")
    finally:
        tracker.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    load_dotenv()
    args = parse_args()
    if args.mode == "convergence-check":
        run_convergence_check()
        return
    if args.mode == "verify-storage":
        run_verify_storage()
        return
    if args.mode == "export-duckdb":
        run_export_duckdb()
        return
    if args.mode == "retrieve-doc":
        run_retrieve_doc(args)
        return
    run_pipeline(args)


if __name__ == "__main__":
    main()
