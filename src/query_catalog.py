from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import CONFIG_DIR

PLACEHOLDER_RE = re.compile(r"\[([A-Z_]+)\]")


@dataclass(frozen=True)
class CatalogQuery:
    query_text: str
    family: str
    stage: int
    stage_name: str
    base_query: str
    temporal_variant: str | None
    required_fields: tuple[str, ...]
    max_results: int


@dataclass(frozen=True)
class SkippedQuery:
    template: str
    family: str
    stage: int
    reason: str


def load_web_query_catalog(path: Path | None = None) -> dict[str, Any]:
    catalog_path = path or CONFIG_DIR / "web_query_catalog.json"
    with catalog_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    text = " ".join(str(value).strip().split())
    if not text or text.lower() in {"none", "null", "nan", "n/a", "unknown"}:
        return None
    return text


def _split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        text_value = str(value)
        raw_items = re.split(r"[,;/|]|\band\b", text_value, flags=re.IGNORECASE)
        if len(raw_items) == 1:
            words = text_value.split()
            if len(words) > 2 and all(word[:1].isupper() or word.isupper() for word in words):
                raw_items = words
    values: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(text)
    return values


def _parse_city(company: dict[str, Any]) -> str | None:
    explicit = _clean_text(company.get("city"))
    if explicit:
        return explicit
    location = _clean_text(company.get("location") or company.get("updated_location"))
    if location and "," in location:
        return _clean_text(location.split(",", 1)[0])
    return location


def _parse_county(company: dict[str, Any]) -> str | None:
    explicit = _clean_text(company.get("county"))
    if explicit:
        return explicit
    location = _clean_text(company.get("location") or company.get("updated_location"))
    if not location:
        return None
    match = re.search(r"([^,]+County)", location, flags=re.IGNORECASE)
    return _clean_text(match.group(1)) if match else None


def _parse_state(company: dict[str, Any], catalog: dict[str, Any]) -> str | None:
    explicit = _clean_text(company.get("state"))
    if explicit:
        return explicit
    address = _clean_text(company.get("address"))
    state_abbrev = _clean_text(catalog.get("default_state_abbrev"))
    if address and state_abbrev and re.search(rf"\b{re.escape(state_abbrev)}\b", address):
        return _clean_text(catalog.get("default_state"))
    return None


def _address_fragment(address: str | None) -> str | None:
    if not address:
        return None
    before_city = address.split(",", 1)[0]
    parts = before_city.split()
    if len(parts) < 2:
        return _clean_text(before_city)
    return _clean_text(" ".join(parts[: min(4, len(parts))]))


def build_company_context(company: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, list[str]]:
    active_catalog = catalog or load_web_query_catalog()
    aliases = _split_values(company.get("company_aliases") or company.get("aliases") or company.get("known_aliases"))
    primary_oems = _split_values(company.get("primary_oems") or company.get("primary_oem"))
    address = _clean_text(company.get("address"))
    values: dict[str, list[str]] = {
        "COMPANY": [value for value in [_clean_text(company.get("company_name"))] if value],
        "COMPANY_ID": [value for value in [_clean_text(company.get("company_id") or company.get("id"))] if value],
        "COMPANY_ALIAS": aliases,
        "CITY": [value for value in [_parse_city(company)] if value],
        "COUNTY": [value for value in [_parse_county(company)] if value],
        "STATE": [value for value in [_parse_state(company, active_catalog)] if value],
        "ADDRESS": [value for value in [address] if value],
        "ADDRESS_FRAGMENT": [value for value in [_address_fragment(address)] if value],
        "PRODUCT_SERVICE": [value for value in [_clean_text(company.get("product_service"))] if value],
        "EV_ROLE": [value for value in [_clean_text(company.get("ev_supply_chain_role") or company.get("ev_role"))] if value],
        "FACILITY_TYPE": [value for value in [_clean_text(company.get("facility_type"))] if value],
        "INDUSTRY_GROUP": [value for value in [_clean_text(company.get("industry_group"))] if value],
        "PRIMARY_OEM": primary_oems,
        "SUPPLIER_TYPE": [
            value
            for value in [_clean_text(company.get("supplier_type") or company.get("supplier_affiliation_type"))]
            if value
        ],
        "CATEGORY": [value for value in [_clean_text(company.get("category"))] if value],
        "TRUSTED_DOMAIN": list(active_catalog.get("trusted_domains", [])),
        "TRUSTED_NEWS_OR_TRADE_DOMAIN": list(active_catalog.get("trusted_news_or_trade_domains", [])),
    }
    return values


def ev_relevance_key(company: dict[str, Any]) -> str:
    raw = _clean_text(company.get("ev_battery_relevant") or company.get("ev_relevant")) or "unknown"
    normalized = raw.lower()
    if normalized in {"yes", "y", "true", "direct"}:
        return "yes"
    if normalized in {"indirect", "partial"}:
        return "indirect"
    if normalized in {"no", "n", "false"}:
        return "no"
    return "unknown"


def query_budget(company: dict[str, Any], catalog: dict[str, Any] | None = None, *, use_max: bool = False) -> int:
    active_catalog = catalog or load_web_query_catalog()
    budgets = active_catalog.get("query_budgets", {})
    budget = budgets.get(ev_relevance_key(company), budgets.get("unknown", {"default": 12, "max": 15}))
    return int(budget["max" if use_max else "default"])


def _trigger_enabled(trigger: str | None, company: dict[str, Any], context: dict[str, list[str]], *, include_fresh: bool) -> bool:
    if not trigger:
        return True
    ev_key = ev_relevance_key(company)
    facility_terms = " ".join(context.get("FACILITY_TYPE", [])).lower()
    role_terms = " ".join(context.get("EV_ROLE", [])).lower()
    industry_terms = " ".join(context.get("INDUSTRY_GROUP", [])).lower()
    product_terms = " ".join(context.get("PRODUCT_SERVICE", [])).lower()
    if trigger == "facility_gap":
        return not (context.get("ADDRESS") and context.get("CITY") and context.get("COUNTY"))
    if trigger == "product_gap":
        return not context.get("PRODUCT_SERVICE") or not context.get("INDUSTRY_GROUP")
    if trigger == "ev_relevant":
        return ev_key in {"yes", "indirect"}
    if trigger == "primary_oems_present":
        return bool(context.get("PRIMARY_OEM"))
    if trigger == "important_manufacturing":
        combined = " ".join([facility_terms, role_terms, industry_terms, product_terms])
        return ev_key == "yes" or any(term in combined for term in ("manufact", "battery", "chemical", "plant"))
    if trigger == "regulatory_relevant":
        combined = " ".join([facility_terms, role_terms, industry_terms, product_terms])
        return any(term in combined for term in ("manufact", "battery", "chemical", "plant", "logistics"))
    if trigger == "identity_ambiguous":
        name = context.get("COMPANY", [""])[0]
        return len(name.split()) <= 2 or bool(context.get("COMPANY_ALIAS"))
    if trigger == "freshness_required":
        return include_fresh
    return False


def _expand_template(template: str, context: dict[str, list[str]]) -> list[str]:
    placeholders = PLACEHOLDER_RE.findall(template)
    queries = [template]
    for placeholder in placeholders:
        values = context.get(placeholder, [])
        if not values:
            return []
        next_queries = []
        for query in queries:
            for value in values:
                next_queries.append(query.replace(f"[{placeholder}]", value))
        queries = next_queries
    return [" ".join(query.split()) for query in queries]


def _with_temporal_variants(base_query: str, catalog: dict[str, Any], enabled: bool) -> list[tuple[str, str | None]]:
    values: list[tuple[str, str | None]] = [(base_query, None)]
    if not enabled:
        return values
    for variant in catalog.get("temporal_variants", []):
        values.append((f"{base_query} {variant}", str(variant)))
    return values


def generate_company_queries(
    company: dict[str, Any],
    catalog: dict[str, Any] | None = None,
    *,
    include_gap: bool = True,
    include_fresh: bool = False,
    use_max_budget: bool = False,
    max_results: int = 10,
) -> tuple[list[CatalogQuery], list[SkippedQuery]]:
    active_catalog = catalog or load_web_query_catalog()
    context = build_company_context(company, active_catalog)
    generated: list[CatalogQuery] = []
    temporal_pending: list[CatalogQuery] = []
    skipped: list[SkippedQuery] = []
    seen: set[str] = set()
    family_counts: dict[str, int] = {}
    family_caps = {str(key): int(value) for key, value in active_catalog.get("family_query_caps", {}).items()}
    for stage in active_catalog.get("stages", []):
        stage_number = int(stage["stage"])
        stage_name = str(stage["name"])
        if stage_number == 2 and not include_gap:
            continue
        for family in stage.get("families", []):
            trigger = family.get("trigger")
            if not _trigger_enabled(trigger, company, context, include_fresh=include_fresh):
                for template_row in family.get("templates", []):
                    skipped.append(
                        SkippedQuery(
                            template=template_row["template"],
                            family=family["family"],
                            stage=stage_number,
                            reason=f"trigger_disabled:{trigger}",
                        )
                    )
                continue
            for template_row in family.get("templates", []):
                required = tuple(template_row.get("required", []))
                missing = [field for field in required if not context.get(field)]
                if missing:
                    skipped.append(
                        SkippedQuery(
                            template=template_row["template"],
                            family=family["family"],
                            stage=stage_number,
                            reason="missing:" + ",".join(missing),
                        )
                    )
                    continue
                for base_query in _expand_template(template_row["template"], context):
                    cap = family_caps.get(str(family["family"]))
                    if cap is not None and family_counts.get(str(family["family"]), 0) >= cap:
                        skipped.append(
                            SkippedQuery(
                                template=base_query,
                                family=family["family"],
                                stage=stage_number,
                                reason=f"family_cap_exceeded:{family['family']}:{cap}",
                            )
                        )
                        continue
                    family_counts[str(family["family"])] = family_counts.get(str(family["family"]), 0) + 1
                    for query_text, temporal_variant in _with_temporal_variants(
                        base_query, active_catalog, bool(family.get("temporal", False))
                    ):
                        normalized = " ".join(query_text.lower().split())
                        if normalized in seen:
                            continue
                        seen.add(normalized)
                        query = CatalogQuery(
                            query_text=query_text,
                            family=family["family"],
                            stage=stage_number,
                            stage_name=stage_name,
                            base_query=base_query,
                            temporal_variant=temporal_variant,
                            required_fields=required,
                            max_results=max_results,
                        )
                        if temporal_variant:
                            temporal_pending.append(query)
                        else:
                            generated.append(query)
    generated.extend(temporal_pending)
    limit = query_budget(company, active_catalog, use_max=use_max_budget)
    if len(generated) > limit:
        for item in generated[limit:]:
            skipped.append(
                SkippedQuery(
                    template=item.base_query,
                    family=item.family,
                    stage=item.stage,
                    reason=f"budget_exceeded:{limit}",
                )
            )
        generated = generated[:limit]
    return generated, skipped


def build_oem_anchor_vocabulary(companies: list[dict[str, Any]], limit: int = 50) -> list[str]:
    seen: set[str] = set()
    anchors: list[str] = []
    for company in companies:
        for value in _split_values(company.get("primary_oems") or company.get("primary_oem")):
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            anchors.append(value)
            if len(anchors) >= limit:
                return anchors
    return anchors


def generate_domain_queries(
    companies: list[dict[str, Any]],
    catalog: dict[str, Any] | None = None,
    *,
    max_results: int = 20,
) -> tuple[list[CatalogQuery], list[SkippedQuery]]:
    active_catalog = catalog or load_web_query_catalog()
    context = {
        "STATE": [_clean_text(active_catalog.get("default_state"))] if _clean_text(active_catalog.get("default_state")) else [],
        "OEM_ANCHOR": build_oem_anchor_vocabulary(companies),
    }
    generated: list[CatalogQuery] = []
    skipped: list[SkippedQuery] = []
    seen: set[str] = set()
    for template_row in active_catalog.get("domain_wide_templates", []):
        required = tuple(template_row.get("required", []))
        missing = [field for field in required if not context.get(field)]
        if missing:
            skipped.append(
                SkippedQuery(
                    template=template_row["template"],
                    family="domain_wide",
                    stage=4,
                    reason="missing:" + ",".join(missing),
                )
            )
            continue
        for query_text in _expand_template(template_row["template"], context):
            normalized = " ".join(query_text.lower().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            generated.append(
                CatalogQuery(
                    query_text=query_text,
                    family="domain_wide",
                    stage=4,
                    stage_name="domain_wide",
                    base_query=query_text,
                    temporal_variant=None,
                    required_fields=required,
                    max_results=max_results,
                )
            )
    return generated, skipped


def company_id(company: dict[str, Any]) -> str | None:
    return _clean_text(company.get("company_id") or company.get("id"))
