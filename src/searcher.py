from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any
from urllib.parse import quote, urlsplit

from src import CONFIG_DIR, iso_now, load_yaml
from src.tracker import DOMAIN_WIDE_COMPANY, Tracker

LOGGER = logging.getLogger(__name__)

QUERY_FAMILIES: dict[int, list[str]] = {
    1: [
        "[COMPANY] Georgia",
        "[COMPANY] [LOCATION]",
        "[COMPANY] Georgia facility",
        "[COMPANY] Georgia operations",
    ],
    2: [
        "[COMPANY] Georgia 2022",
        "[COMPANY] Georgia 2023",
        "[COMPANY] Georgia 2024",
        "[COMPANY] Georgia 2025",
        "[COMPANY] Georgia 2026",
        "[COMPANY] Georgia latest",
        "[COMPANY] Georgia recent",
        "[COMPANY] Georgia current",
    ],
    3: [
        "[COMPANY] Georgia investment",
        "[COMPANY] Georgia jobs created",
        "[COMPANY] Georgia capital expenditure",
        "[COMPANY] Georgia expansion announcement",
        "[COMPANY] Georgia plant capacity",
    ],
    4: [
        "[COMPANY] Georgia supplier",
        "[COMPANY] Georgia OEM customer",
        "[COMPANY] Georgia supply chain",
        "[COMPANY] Kia Georgia",
        "[COMPANY] Hyundai Metaplant",
        "[COMPANY] SK On",
    ],
    5: [
        "[COMPANY] electric vehicle",
        "[COMPANY] EV battery",
        "[COMPANY] battery manufacturing",
        "[COMPANY] lithium ion",
        "[COMPANY] EV supply chain Georgia",
    ],
    6: [
        "[COMPANY] Georgia press release",
        "[COMPANY] Georgia annual report",
        "[COMPANY] Georgia permit",
        "[COMPANY] Georgia SEC filing",
        "[COMPANY] Georgia PDF",
        "[COMPANY] Georgia announcement site:georgia.org",
        "[COMPANY] site:sec.gov",
        "[COMPANY] site:energy.gov",
    ],
    7: [
        "[COMPANY] Georgia economic development",
        "[COMPANY] Georgia GDEcD",
        "[COMPANY] Georgia governor announcement",
        "[COMPANY] Georgia tax incentive",
    ],
    8: [
        "[COMPANY] Georgia news",
        "[COMPANY] Georgia autonews",
        "[COMPANY] Georgia Reuters",
        "[COMPANY] Georgia Bloomberg",
        "[COMPANY] Georgia manufacturing news",
    ],
}

TEMPORAL_FAMILIES = {3, 6, 7, 8}
TEMPORAL_VARIANTS = [
    ("yearless", None),
    ("2022", "2022"),
    ("2023", "2023"),
    ("2024", "2024"),
    ("2025", "2025"),
    ("2026", "2026"),
    ("latest", "latest"),
    ("recent", "recent"),
    ("current", "current"),
]
HIGH_VALUE_FAMILIES = {3, 6, 7, 8}
PRIORITY_DOMAINS = {
    "georgia.org",
    "gov.georgia.gov",
    "selectgeorgia.com",
    "savannahjda.com",
    "sec.gov",
    "energy.gov",
    "permitsearch.gaepd.org",
    "epd.georgia.gov",
    "gaports.com",
    "hmgma.com",
    "kiageorgia.com",
    "skon.co",
    "hitachiastemo.com",
    "emobility.uga.edu",
    "autonews.com",
    "importyeti.com",
    "marklines.com",
}

_LAST_DDG_QUERY_AT = 0.0


def _load_settings() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "settings.yaml")


def _normalize_query_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _fill_company_template(template: str, company: dict[str, Any]) -> str:
    return (
        template.replace("[COMPANY]", company["company_name"])
        .replace("[LOCATION]", company.get("location") or "Georgia")
        .strip()
    )


def load_companies() -> list[dict[str, Any]]:
    with (CONFIG_DIR / "companies.json").open("r", encoding="utf-8") as handle:
        companies = json.load(handle)
    return sorted(companies, key=lambda item: (item["priority"], item["company_name"].lower()))


def load_seed_urls() -> list[dict[str, Any]]:
    with (CONFIG_DIR / "seed_urls.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_domain_queries() -> list[str]:
    with (CONFIG_DIR / "domain_queries.json").open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_blocklist() -> set[str]:
    with (CONFIG_DIR / "blocklist.json").open("r", encoding="utf-8") as handle:
        return set(json.load(handle))


def build_temporal_variants(base_query: str) -> list[dict[str, Any]]:
    variants = []
    for variant_name, suffix in TEMPORAL_VARIANTS:
        query_text = base_query if suffix is None else f"{base_query} {suffix}"
        variants.append({"query_text": query_text, "temporal_variant": variant_name, "base_query": base_query})
    return variants


def build_query_bundle(company: dict[str, Any], tracker: Tracker | None = None) -> list[dict[str, Any]]:
    settings = _load_settings()
    queries: list[dict[str, Any]] = []
    families = company["query_families"]
    for family in families:
        templates = QUERY_FAMILIES[family]
        for template in templates:
            base_query = _fill_company_template(template, company)
            if family in TEMPORAL_FAMILIES:
                variants = build_temporal_variants(base_query)
                for variant in variants:
                    queries.append(
                        {
                            "query_text": variant["query_text"],
                            "family": family,
                            "company_name": company["company_name"],
                            "base_query": base_query,
                            "temporal_variant": variant["temporal_variant"],
                            "max_results": settings["ddg_max_results_high_value_families"],
                        }
                    )
            else:
                queries.append(
                    {
                        "query_text": base_query,
                        "family": family,
                        "company_name": company["company_name"],
                        "base_query": base_query,
                        "temporal_variant": None,
                        "max_results": (
                            settings["ddg_max_results_high_value_families"]
                            if family in HIGH_VALUE_FAMILIES
                            else settings["ddg_max_results_standard_families"]
                        ),
                    }
                )
    temporal_config = {
        "temporal_families": sorted(TEMPORAL_FAMILIES),
        "variants": [name for name, _ in TEMPORAL_VARIANTS],
        "yearless_first": True,
    }
    query_set_hash = tracker.compute_query_set_hash(queries, temporal_config) if tracker else ""
    seen_normalized: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for query in queries:
        normalized = _normalize_query_text(query["query_text"])
        if normalized in seen_normalized:
            continue
        seen_normalized.add(normalized)
        item = dict(query)
        item["query_set_hash"] = query_set_hash
        deduped.append(item)
    if tracker is not None:
        return tracker.get_unconverged_queries(company["company_name"], deduped)
    return deduped


def _rate_limit_ddg() -> None:
    global _LAST_DDG_QUERY_AT
    delay = float(_load_settings()["ddg_query_delay"])
    now = time.monotonic()
    elapsed = now - _LAST_DDG_QUERY_AT
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _LAST_DDG_QUERY_AT = time.monotonic()


def search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    _rate_limit_ddg()
    settings = _load_settings()
    for attempt in range(1, 4):
        try:
            from ddgs import DDGS
            from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

            results = DDGS().text(
                query,
                backend=settings["ddg_backend"],
                region=settings["ddg_region"],
                max_results=max_results,
            )
            normalized_results = []
            for result in results or []:
                normalized_results.append(
                    {
                        "url": result.get("href") or result.get("url") or "",
                        "title": result.get("title") or "",
                        "snippet": result.get("body") or result.get("snippet") or "",
                    }
                )
            LOGGER.info("DDG query complete: %s | results=%s", query, len(normalized_results))
            return normalized_results
        except (RatelimitException, TimeoutException) as exc:
            LOGGER.warning("DDG query failed (attempt %s): %s | %s", attempt, query, exc)
            time.sleep(float(settings["ddg_query_delay"]) * (2 ** (attempt - 1)))
        except DDGSException as exc:
            if "no results found" in str(exc).lower():
                LOGGER.info("DDG query complete: %s | results=0", query)
                return []
            LOGGER.warning("DDG query failed (attempt %s): %s | %s", attempt, query, exc)
            time.sleep(float(settings["ddg_query_delay"]) * (2 ** (attempt - 1)))
        except Exception as exc:
            LOGGER.warning("DDG query failed (attempt %s): %s | %s", attempt, query, exc)
            time.sleep(float(settings["ddg_query_delay"]) * (2 ** (attempt - 1)))
    return []


def score_url_relevance(url: str, title: str, snippet: str) -> float:
    combined = f"{url} {title} {snippet}".lower()
    score = 0.0
    keyword_weights = {
        "georgia": 0.1,
        "battery": 0.12,
        "electric vehicle": 0.12,
        "ev": 0.08,
        "supplier": 0.08,
        "manufacturing": 0.08,
        "plant": 0.08,
        "facility": 0.06,
        "investment": 0.08,
        "jobs": 0.06,
        "economic development": 0.08,
        "permit": 0.08,
        "sec": 0.05,
        "press release": 0.06,
        "hyundai": 0.08,
        "kia": 0.08,
        "sk on": 0.08,
        "hmgma": 0.08,
        "bryan county": 0.08,
        "jackson county": 0.06,
    }
    for keyword, weight in keyword_weights.items():
        if keyword in combined:
            score += weight
    domain = urlsplit(url).netloc.lower()
    for priority_domain in PRIORITY_DOMAINS:
        if domain == priority_domain or domain.endswith(f".{priority_domain}"):
            score += 0.3
            break
    return round(min(score, 1.0), 3)


def _run_query(tracker: Tracker, company_name: str, query: dict[str, Any], min_score: float) -> dict[str, Any]:
    results = search_duckduckgo(query["query_text"], int(query["max_results"]))
    new_urls = 0
    known_urls = 0
    filtered_urls = 0
    discovered_urls: list[str] = []
    relevance_total = 0.0
    for result in results:
        url = result["url"]
        if not url:
            continue
        score = score_url_relevance(url, result["title"], result["snippet"])
        relevance_total += score
        blocked = is_blocked(url)
        note_parts: list[str] = []
        if blocked:
            note_parts.append("Blocked by configured domain blocklist")
        if score < min_score:
            note_parts.append("Below relevance threshold")
        is_new = tracker.add_url(
            url,
            query["query_text"],
            company_name,
            result["title"],
            result["snippet"],
            relevance_score=score,
            blocked=blocked,
            priority_domain=_is_priority_domain(url),
            source_backend="duckduckgo",
            url_type="document",
            notes="; ".join(note_parts) if note_parts else None,
        )
        tracker.add_url_company_mapping(url, company_name, query["query_text"])
        eligible_for_download = not blocked and score >= min_score
        if not eligible_for_download:
            if is_new:
                filtered_urls += 1
            else:
                known_urls += 1
            continue
        if is_new:
            new_urls += 1
            discovered_urls.append(url)
            continue
        existing_record = tracker.get_url_record(url) or {}
        if not existing_record.get("last_download_status"):
            discovered_urls.append(url)
        else:
            known_urls += 1
    avg_relevance = round(relevance_total / len(results), 4) if results else 0.0
    LOGGER.info(
        "Query processed: %s | total=%s | new=%s | known=%s | filtered=%s",
        query["query_text"],
        len(results),
        new_urls,
        known_urls,
        filtered_urls,
    )
    tracker.update_query_convergence(
        company_name,
        query["query_text"],
        query["family"],
        query["temporal_variant"],
        query["query_set_hash"],
        new_urls,
        query["run_id"],
        urls_found_count=len(results),
    )
    tracker.update_query_performance(
        company_name,
        query["query_text"],
        query["family"],
        len(results),
        new_urls,
        avg_relevance,
        downloaded_ok=0,
        duplicates=0,
    )
    return {
        "query_text": query["query_text"],
        "family": query["family"],
        "temporal_variant": query["temporal_variant"],
        "urls_found": len(results),
        "new_urls": new_urls,
        "known_urls": known_urls,
        "filtered_urls": filtered_urls,
        "avg_relevance": avg_relevance,
        "discovered_urls": discovered_urls,
    }


def collect_for_company(company: dict[str, Any], tracker: Tracker, run_id: str) -> dict[str, Any]:
    settings = _load_settings()
    min_score = float(settings["relevance_min_score"])
    bundle = build_query_bundle(company, tracker)
    for query in bundle:
        query["run_id"] = run_id
    base_groups: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    ordered_non_temporal: list[dict[str, Any]] = []
    for query in bundle:
        if query["family"] in TEMPORAL_FAMILIES:
            base_groups[(query["family"], query["base_query"])].append(query)
        else:
            ordered_non_temporal.append(query)
    query_stats: list[dict[str, Any]] = []
    discovered_urls: list[str] = []
    for query in ordered_non_temporal:
        stats = _run_query(tracker, company["company_name"], query, min_score)
        query_stats.append(stats)
        discovered_urls.extend(stats["discovered_urls"])
    for _, variants in base_groups.items():
        ordered = sorted(
            variants,
            key=lambda item: [name for name, _ in TEMPORAL_VARIANTS].index(item["temporal_variant"]),
        )
        yearless = ordered[0]
        stats = _run_query(tracker, company["company_name"], yearless, min_score)
        query_stats.append(stats)
        discovered_urls.extend(stats["discovered_urls"])
        if stats["new_urls"] == 0:
            continue
        for variant in ordered[1:]:
            variant_stats = _run_query(tracker, company["company_name"], variant, min_score)
            query_stats.append(variant_stats)
            discovered_urls.extend(variant_stats["discovered_urls"])
    company_convergence = tracker.get_company_convergence_record(company["company_name"])
    return {
        "company_name": company["company_name"],
        "run_id": run_id,
        "query_stats": query_stats,
        "discovered_urls": list(dict.fromkeys(discovered_urls)),
        "company_convergence": company_convergence,
        "processed_at": iso_now(),
    }


def collect_domain_wide(tracker: Tracker, run_id: str) -> dict[str, Any]:
    settings = _load_settings()
    base_queries = load_domain_queries()
    min_score = float(settings["relevance_min_score"])
    bundle: list[dict[str, Any]] = []
    for base_query in base_queries:
        variants = build_temporal_variants(base_query)
        for variant in variants:
            bundle.append(
                {
                    "query_text": variant["query_text"],
                    "family": 0,
                    "company_name": DOMAIN_WIDE_COMPANY,
                    "base_query": base_query,
                    "temporal_variant": variant["temporal_variant"],
                    "max_results": settings["ddg_max_results_high_value_families"],
                    "run_id": run_id,
                }
            )
    temporal_config = {
        "temporal_families": [0],
        "variants": [name for name, _ in TEMPORAL_VARIANTS],
        "yearless_first": True,
    }
    query_set_hash = tracker.compute_query_set_hash(bundle, temporal_config)
    for query in bundle:
        query["query_set_hash"] = query_set_hash
    bundle = tracker.get_unconverged_queries(DOMAIN_WIDE_COMPANY, bundle)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for query in bundle:
        grouped[query["base_query"]].append(query)
    query_stats: list[dict[str, Any]] = []
    discovered_urls: list[str] = []
    for base_query in base_queries:
        variants = grouped.get(base_query, [])
        if not variants:
            continue
        ordered = sorted(
            variants,
            key=lambda item: [name for name, _ in TEMPORAL_VARIANTS].index(item["temporal_variant"]),
        )
        yearless_stats = _run_query(tracker, DOMAIN_WIDE_COMPANY, ordered[0], min_score)
        query_stats.append(yearless_stats)
        discovered_urls.extend(yearless_stats["discovered_urls"])
        if yearless_stats["new_urls"] == 0:
            continue
        for variant in ordered[1:]:
            stats = _run_query(tracker, DOMAIN_WIDE_COMPANY, variant, min_score)
            query_stats.append(stats)
            discovered_urls.extend(stats["discovered_urls"])
    return {
        "company_name": DOMAIN_WIDE_COMPANY,
        "run_id": run_id,
        "query_stats": query_stats,
        "discovered_urls": list(dict.fromkeys(discovered_urls)),
    }


def _generate_search_portal_records(seed_entry: dict[str, Any], companies: list[dict[str, Any]]) -> list[dict[str, str]]:
    if seed_entry.get("enabled", True) is False:
        return []
    records: list[dict[str, str]] = []
    for company in companies:
        encoded_name = quote(company["company_name"], safe="")
        for pattern in seed_entry.get("search_portal_queries", []):
            records.append(
                {
                    "url": pattern.replace("[COMPANY]", encoded_name),
                    "company_name": company["company_name"],
                    "source_url": seed_entry["url"],
                }
            )
    return records


def generate_search_portal_urls(seed_entry: dict[str, Any], companies: list[dict[str, Any]]) -> list[str]:
    return [record["url"] for record in _generate_search_portal_records(seed_entry, companies)]


def generate_search_portal_url_records(seed_entry: dict[str, Any], companies: list[dict[str, Any]]) -> list[dict[str, str]]:
    return _generate_search_portal_records(seed_entry, companies)


def _is_priority_domain(url: str) -> bool:
    domain = urlsplit(url).netloc.lower()
    return any(domain == item or domain.endswith(f".{item}") for item in PRIORITY_DOMAINS)


def is_blocked(url: str) -> bool:
    domain = urlsplit(url).netloc.lower()
    normalized = url.lower()
    for blocked in load_blocklist():
        if "/" in blocked:
            if blocked in normalized:
                return True
        elif domain == blocked or domain.endswith(f".{blocked}"):
            return True
    return False
