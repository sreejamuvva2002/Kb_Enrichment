from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any
from urllib.parse import quote, urlsplit

from src import CONFIG_DIR, iso_now, load_yaml
from src.query_catalog import (
    CatalogQuery,
    build_company_context,
    generate_company_queries,
    generate_domain_queries,
    load_web_query_catalog,
)
from src.tavily_client import TavilySearchClient
from src.tracker import DOMAIN_WIDE_COMPANY, Tracker

LOGGER = logging.getLogger(__name__)

_LAST_DDG_QUERY_AT = 0.0
_LAST_TAVILY_QUERY_AT = 0.0
_TAVILY_CLIENT: TavilySearchClient | None = None


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


def build_query_bundle(
    company: dict[str, Any],
    tracker: Tracker | None = None,
    *,
    include_gap: bool = True,
    include_fresh: bool = False,
) -> list[dict[str, Any]]:
    settings = _load_settings()
    catalog = load_web_query_catalog()
    generated, _ = generate_company_queries(
        company,
        catalog,
        include_gap=include_gap,
        include_fresh=include_fresh,
        max_results=int(settings["ddg_max_results_standard_families"]),
    )
    temporal_config = {"catalog_version": catalog.get("version"), "include_gap": include_gap, "include_fresh": include_fresh}
    query_set_hash = tracker.compute_query_set_hash([item.__dict__ for item in generated], temporal_config) if tracker else ""
    deduped = [
        {
            "query_text": query.query_text,
            "family": query.family,
            "query_family": query.family,
            "query_stage": query.stage,
            "stage_name": query.stage_name,
            "company_name": company["company_name"],
            "company_id": company.get("company_id") or company.get("id"),
            "base_query": query.base_query,
            "temporal_variant": query.temporal_variant,
            "max_results": query.max_results,
            "query_set_hash": query_set_hash,
        }
        for query in generated
    ]
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


def _rate_limit_tavily() -> None:
    global _LAST_TAVILY_QUERY_AT
    delay = float(_load_settings().get("tavily_query_delay", 0.0))
    now = time.monotonic()
    elapsed = now - _LAST_TAVILY_QUERY_AT
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _LAST_TAVILY_QUERY_AT = time.monotonic()


def _get_tavily_client() -> TavilySearchClient:
    global _TAVILY_CLIENT
    if _TAVILY_CLIENT is None:
        _TAVILY_CLIENT = TavilySearchClient(_load_settings())
    return _TAVILY_CLIENT


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
                        "source_backend": "duckduckgo",
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


def search_tavily(query: str, max_results: int) -> list[dict[str, Any]]:
    _rate_limit_tavily()
    client = _get_tavily_client()
    results = client.search(query, max_results)
    LOGGER.info("Tavily query complete: %s | results=%s", query, len(results))
    return results


def search_web(query: str, max_results: int) -> list[dict[str, Any]]:
    settings = _load_settings()
    backend = str(settings.get("search_backend", "duckduckgo")).lower()
    fallback = str(settings.get("search_fallback_backend", "") or "").lower()
    if backend == "tavily":
        try:
            return search_tavily(query, max_results)
        except Exception as exc:
            if fallback == "duckduckgo":
                LOGGER.warning("Tavily query failed; falling back to DuckDuckGo: %s | %s", query, exc)
                return search_duckduckgo(query, max_results)
            raise
    if backend == "duckduckgo":
        return search_duckduckgo(query, max_results)
    raise ValueError(f"Unsupported search_backend: {backend}")


def _source_profile(url: str) -> tuple[int, str | None]:
    catalog = load_web_query_catalog()
    domain = urlsplit(url).netloc.lower()
    for source_type, row in catalog.get("source_priority_domains", {}).items():
        for priority_domain in row.get("domains", []):
            if domain == priority_domain or domain.endswith(f".{priority_domain}"):
                return int(row.get("priority", 7)), source_type
    return 7, None


def _contains_any(text: str, values: list[str]) -> bool:
    return any(value and value.lower() in text for value in values)


def score_url_relevance(url: str, title: str, snippet: str, company: dict[str, Any] | None = None) -> float:
    combined = f"{url} {title} {snippet}".lower()
    score = 0.0
    catalog = load_web_query_catalog()
    context = build_company_context(company, catalog) if company else {}
    if company and company.get("company_name") == DOMAIN_WIDE_COMPANY and not context.get("STATE"):
        context["STATE"] = [str(catalog.get("default_state"))] if catalog.get("default_state") else []
    if company and _contains_any(combined, context.get("COMPANY", []) + context.get("COMPANY_ALIAS", [])):
        score += 0.25
    for field, weight in [
        ("CITY", 0.08),
        ("COUNTY", 0.08),
        ("STATE", 0.08),
        ("PRODUCT_SERVICE", 0.12),
        ("EV_ROLE", 0.12),
        ("FACILITY_TYPE", 0.08),
        ("INDUSTRY_GROUP", 0.06),
        ("PRIMARY_OEM", 0.08),
    ]:
        if _contains_any(combined, context.get(field, [])):
            score += weight
    for term_group, weight in [
        ("ev_terms", 0.08),
        ("relationship_terms", 0.05),
        ("investment_terms", 0.06),
        ("regulatory_terms", 0.06),
        ("ownership_terms", 0.04),
    ]:
        if _contains_any(combined, [str(item) for item in catalog.get(term_group, [])]):
            score += weight
    source_priority, _ = _source_profile(url)
    if source_priority <= 4:
        score += 0.25
    elif source_priority <= 6:
        score += 0.1
    return round(min(score, 1.0), 3)


def _family_requires_geo(family: str) -> bool:
    return family in {
        "facility_location",
        "investment_jobs_capacity",
        "government_economic_development",
        "regulatory_permit",
        "news_recent_activity",
    }


def _relationship_signal(text: str, catalog: dict[str, Any]) -> bool:
    return _contains_any(text, [str(item) for item in catalog.get("relationship_terms", [])])


def evaluate_search_result(
    url: str,
    title: str,
    snippet: str,
    company: dict[str, Any],
    query: dict[str, Any],
    min_score: float,
) -> dict[str, Any]:
    catalog = load_web_query_catalog()
    context = build_company_context(company, catalog)
    if company.get("company_name") == DOMAIN_WIDE_COMPANY and not context.get("STATE"):
        context["STATE"] = [str(catalog.get("default_state"))] if catalog.get("default_state") else []
    combined = f"{url} {title} {snippet}".lower()
    source_priority, source_type = _source_profile(url)
    blocked = is_blocked(url)
    score = score_url_relevance(url, title, snippet, company)
    domain_wide = company.get("company_name") == DOMAIN_WIDE_COMPANY
    company_match = domain_wide or _contains_any(combined, context.get("COMPANY", []) + context.get("COMPANY_ALIAS", []))
    geo_values = (
        context.get("STATE", [])
        + [catalog.get("default_state_abbrev", "")]
        + context.get("CITY", [])
        + context.get("COUNTY", [])
        + context.get("ADDRESS_FRAGMENT", [])
    )
    geography_match = _contains_any(combined, [str(value) for value in geo_values if value])
    product_match = _contains_any(
        combined,
        context.get("PRODUCT_SERVICE", []) + context.get("EV_ROLE", []) + context.get("INDUSTRY_GROUP", []),
    )
    family = str(query.get("family") or query.get("query_family") or "")
    reasons: list[str] = []
    if blocked:
        reasons.append("blocked_domain")
    if score < min_score:
        reasons.append("below_relevance_threshold")
    if not company_match:
        reasons.append("company_entity_not_matched")
    if domain_wide and not (
        geography_match
        and (
            _contains_any(combined, [str(item) for item in catalog.get("ev_terms", [])])
            or _contains_any(combined, [str(item) for item in catalog.get("investment_terms", [])])
            or _contains_any(combined, [str(item) for item in catalog.get("regulatory_terms", [])])
            or source_priority <= 4
        )
    ):
        reasons.append("domain_wide_topic_or_geography_not_matched")
    if _family_requires_geo(family) and not geography_match:
        reasons.append("geography_not_matched")
    if family == "product_service" and not product_match and source_priority > 4:
        reasons.append("product_or_industry_not_matched")
    if family == "ev_battery_relevance" and not (
        product_match or _contains_any(combined, [str(item) for item in catalog.get("ev_terms", [])])
    ):
        reasons.append("ev_or_battery_signal_not_matched")
    if family == "oem_relationship" and not (
        _contains_any(combined, context.get("PRIMARY_OEM", [])) and _relationship_signal(combined, catalog)
    ):
        reasons.append("oem_relationship_not_matched")
    accepted = not reasons
    confidence = score
    if source_priority <= 4:
        confidence += 0.15
    if geography_match:
        confidence += 0.1
    if product_match:
        confidence += 0.1
    return {
        "accepted": accepted,
        "score": round(min(confidence, 1.0), 3),
        "relevance_score": score,
        "blocked": blocked,
        "source_priority": source_priority,
        "source_type": source_type,
        "rejection_reason": ";".join(reasons) if reasons else None,
    }


def _run_query(tracker: Tracker, company: dict[str, Any], query: dict[str, Any], min_score: float) -> dict[str, Any]:
    results = search_web(query["query_text"], int(query["max_results"]))
    new_urls = 0
    known_urls = 0
    filtered_urls = 0
    discovered_urls: list[str] = []
    relevance_total = 0.0
    for result in results:
        url = result["url"]
        if not url:
            continue
        evaluation = evaluate_search_result(url, result["title"], result["snippet"], company, query, min_score)
        score = evaluation["relevance_score"]
        relevance_total += score
        blocked = bool(evaluation["blocked"])
        note_parts: list[str] = []
        if blocked:
            note_parts.append("Blocked by configured domain blocklist")
        if evaluation.get("rejection_reason"):
            note_parts.append(str(evaluation["rejection_reason"]))
        is_new = tracker.add_url(
            url,
            query["query_text"],
            company["company_name"],
            result["title"],
            result["snippet"],
            company_id=company.get("company_id") or company.get("id"),
            query_family=query.get("query_family") or query.get("family"),
            query_stage=query.get("query_stage"),
            relevance_score=score,
            confidence_score=evaluation["score"],
            blocked=blocked,
            priority_domain=_is_priority_domain(url),
            source_priority=evaluation["source_priority"],
            source_type=evaluation["source_type"],
            source_backend=result.get("source_backend") or str(_load_settings().get("search_backend", "unknown")),
            url_type="document",
            published_date=result.get("published_date"),
            rejection_reason=evaluation.get("rejection_reason"),
            notes="; ".join(note_parts) if note_parts else None,
        )
        tracker.add_url_company_mapping(url, company["company_name"], query["query_text"], company.get("company_id") or company.get("id"))
        eligible_for_download = bool(evaluation["accepted"])
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
        query.get("query_family") or query["family"],
        query["temporal_variant"],
        query["query_set_hash"],
        new_urls,
        query["run_id"],
        urls_found_count=len(results),
    )
    tracker.update_query_performance(
        company_name,
        query["query_text"],
        query.get("query_family") or query["family"],
        len(results),
        new_urls,
        avg_relevance,
        downloaded_ok=0,
        duplicates=0,
    )
    return {
        "query_text": query["query_text"],
        "family": query.get("query_family") or query["family"],
        "stage": query.get("query_stage"),
        "temporal_variant": query["temporal_variant"],
        "urls_found": len(results),
        "new_urls": new_urls,
        "known_urls": known_urls,
        "filtered_urls": filtered_urls,
        "avg_relevance": avg_relevance,
        "discovered_urls": discovered_urls,
    }


def collect_for_company(
    company: dict[str, Any],
    tracker: Tracker,
    run_id: str,
    *,
    include_fresh: bool = False,
) -> dict[str, Any]:
    settings = _load_settings()
    min_score = float(settings["relevance_min_score"])
    bundle = build_query_bundle(company, tracker, include_fresh=include_fresh)
    for query in bundle:
        query["run_id"] = run_id
    base_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    ordered_non_temporal: list[dict[str, Any]] = []
    for query in bundle:
        if query.get("temporal_variant"):
            base_groups[(str(query["family"]), query["base_query"])].append(query)
        else:
            ordered_non_temporal.append(query)
    query_stats: list[dict[str, Any]] = []
    discovered_urls: list[str] = []
    for query in ordered_non_temporal:
        stats = _run_query(tracker, company, query, min_score)
        query_stats.append(stats)
        discovered_urls.extend(stats["discovered_urls"])
    for _, variants in base_groups.items():
        ordered = sorted(
            variants,
            key=lambda item: (item["temporal_variant"] is not None, str(item["temporal_variant"])),
        )
        yearless = ordered[0]
        stats = _run_query(tracker, company, yearless, min_score)
        query_stats.append(stats)
        discovered_urls.extend(stats["discovered_urls"])
        if stats["new_urls"] == 0:
            continue
        for variant in ordered[1:]:
            variant_stats = _run_query(tracker, company, variant, min_score)
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
    min_score = float(settings["relevance_min_score"])
    companies = load_companies()
    generated, _ = generate_domain_queries(
        companies,
        max_results=int(settings["ddg_max_results_high_value_families"]),
    )
    temporal_config = {"catalog": "web_query_catalog", "stage": 4}
    query_set_hash = tracker.compute_query_set_hash([item.__dict__ for item in generated], temporal_config)
    bundle = [
        {
            "query_text": query.query_text,
            "family": query.family,
            "query_family": query.family,
            "query_stage": query.stage,
            "company_name": DOMAIN_WIDE_COMPANY,
            "base_query": query.base_query,
            "temporal_variant": query.temporal_variant,
            "max_results": query.max_results,
            "run_id": run_id,
            "query_set_hash": query_set_hash,
        }
        for query in generated
    ]
    bundle = tracker.get_unconverged_queries(DOMAIN_WIDE_COMPANY, bundle)
    query_stats: list[dict[str, Any]] = []
    discovered_urls: list[str] = []
    domain_company = {"company_name": DOMAIN_WIDE_COMPANY, "company_id": None}
    for query in bundle:
        stats = _run_query(tracker, domain_company, query, min_score)
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
                    "company_id": company.get("company_id") or company.get("id"),
                    "source_url": seed_entry["url"],
                }
            )
    return records


def generate_search_portal_urls(seed_entry: dict[str, Any], companies: list[dict[str, Any]]) -> list[str]:
    return [record["url"] for record in _generate_search_portal_records(seed_entry, companies)]


def generate_search_portal_url_records(seed_entry: dict[str, Any], companies: list[dict[str, Any]]) -> list[dict[str, str]]:
    return _generate_search_portal_records(seed_entry, companies)


def _is_priority_domain(url: str) -> bool:
    priority, _ = _source_profile(url)
    return priority <= 4


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
