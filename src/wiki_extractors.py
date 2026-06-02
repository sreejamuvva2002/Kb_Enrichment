"""
Fallback extractors for wiki facts when LLM extraction fails or is low confidence.
Uses regex and heuristics to extract structured data reliably.
"""

from __future__ import annotations

import re
from typing import Any


class HeuristicExtractor:
    """Fallback entity extraction using regex and pattern matching."""

    # Investment amount patterns: "$50 million", "50M jobs", etc.
    AMOUNT_PATTERN = re.compile(
        r"\$?\d+(?:\.?\d+)?\s*(?:million|M|billion|B|thousand|K)(?:\s+(?:jobs|employees|workers))?"
    )

    # Date patterns: "2024", "Q3 2024", "January 2024"
    DATE_PATTERN = re.compile(
        r"(?:Q[1-4]?\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)?\s*\d{4}|20\d{2}"
    )

    # Location patterns: "Atlanta, Georgia" or "Cobb County"
    LOCATION_PATTERN = re.compile(
        r"(?:in|at|near)\s+([A-Z][a-zA-Z\s]+),?\s*(?:Georgia|GA)"
    )

    # Facility types
    FACILITY_KEYWORDS = {
        "manufacturing": ["manufacturing", "plant", "factory", "production"],
        "battery": ["battery", "cell", "pack", "gigafactory"],
        "assembly": ["assembly", "assembly line", "assembly plant"],
        "warehouse": ["warehouse", "distribution", "logistics"],
        "r&d": ["research", "lab", "development", "testing"],
    }

    # Company relationship indicators
    RELATIONSHIP_KEYWORDS = {
        "supplier": ["supplier", "supplies", "provides", "supplies to"],
        "customer": ["customer", "client", "buyer"],
        "partner": ["partner", "partnership", "collaboration", "joint venture"],
        "parent": ["parent", "owns", "subsidiary", "acquired"],
        "competitor": ["competitor", "competes with", "rival"],
    }

    @staticmethod
    def extract_amounts(text: str) -> list[dict[str, Any]]:
        """Extract investment amounts and job numbers."""
        amounts = []
        for match in HeuristicExtractor.AMOUNT_PATTERN.finditer(text):
            amounts.append(
                {
                    "value": match.group(),
                    "position": match.start(),
                    "context": text[max(0, match.start() - 50) : min(len(text), match.end() + 50)],
                }
            )
        return amounts

    @staticmethod
    def extract_dates(text: str) -> list[str]:
        """Extract dates and years mentioned."""
        return HeuristicExtractor.DATE_PATTERN.findall(text)

    @staticmethod
    def extract_locations(text: str) -> list[str]:
        """Extract Georgia locations (cities, counties)."""
        locations = set()
        for match in HeuristicExtractor.LOCATION_PATTERN.finditer(text):
            locations.add(match.group(1).strip())

        # Also look for explicit county/city mentions
        county_match = re.findall(r"([A-Z][a-z]+\s+County)(?:\s|,|$)", text)
        locations.update(county_match)

        city_match = re.findall(r"(?:^|\s)(Atlanta|Savannah|Augusta|Athens|Columbus|Macon|Marietta)(?:\s|,|$)", text)
        locations.update(city_match)

        return list(locations)

    @staticmethod
    def extract_facility_type(text: str, company_name: str | None = None) -> str | None:
        """Infer facility type from keywords."""
        text_lower = text.lower()
        for facility_type, keywords in HeuristicExtractor.FACILITY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return facility_type
        return None

    @staticmethod
    def extract_relationships(text: str) -> list[dict[str, Any]]:
        """Extract company relationships."""
        relationships = []
        for rel_type, keywords in HeuristicExtractor.RELATIONSHIP_KEYWORDS.items():
            for keyword in keywords:
                # Look for pattern: "Company A [keyword] Company B"
                pattern = rf"([A-Z][a-zA-Z\s&]+?)\s+{re.escape(keyword)}\s+([A-Z][a-zA-Z\s&]+?)(?:\s|,|\.)"
                for match in re.finditer(pattern, text):
                    relationships.append(
                        {
                            "subject": match.group(1).strip(),
                            "relationship_type": rel_type,
                            "object": match.group(2).strip(),
                            "keyword": keyword,
                        }
                    )
        return relationships

    @staticmethod
    def extract_company_mentions(text: str, known_companies: list[str] | None = None) -> list[str]:
        """Extract company names mentioned in text."""
        if not known_companies:
            # Fallback: look for uppercase sequences that look like company names
            companies = set()
            for match in re.finditer(r"([A-Z][a-zA-Z\d&\s]+?)(?:Inc|Corp|Ltd|LLC|Company)(?:\s|,|$)", text):
                company = match.group(1).strip()
                if len(company) > 2 and len(company.split()) <= 5:
                    companies.add(company)
            return list(companies)

        # Check for known companies
        found = set()
        text_lower = text.lower()
        for company in known_companies:
            if company.lower() in text_lower:
                found.add(company)
        return list(found)


def fill_facts_with_heuristics(
    llm_facts: dict[str, Any],
    text: str,
    fallback: bool = True,
) -> dict[str, Any]:
    """
    Enhance or fill gaps in LLM-extracted facts using heuristics.

    Args:
        llm_facts: Facts extracted by LLM
        text: Original text to analyze
        fallback: If True, use heuristics to fill missing fields

    Returns:
        Enhanced facts dict
    """
    if not fallback:
        return llm_facts

    enhanced = dict(llm_facts)

    # Fill missing amounts
    if not enhanced.get("amount") and not enhanced.get("investment"):
        amounts = HeuristicExtractor.extract_amounts(text)
        if amounts:
            enhanced["amounts_mentioned"] = [a["value"] for a in amounts]

    # Fill missing dates
    if not enhanced.get("date") and not enhanced.get("dates"):
        dates = HeuristicExtractor.extract_dates(text)
        if dates:
            enhanced["dates_mentioned"] = dates

    # Fill missing locations
    if not enhanced.get("location"):
        locations = HeuristicExtractor.extract_locations(text)
        if locations:
            enhanced["locations_mentioned"] = locations

    # Infer facility type
    if enhanced.get("entity_type") == "facility" and not enhanced.get("facility_type"):
        facility_type = HeuristicExtractor.extract_facility_type(text, enhanced.get("entity_name"))
        if facility_type:
            enhanced["facility_type"] = facility_type

    # Extract relationships
    if not enhanced.get("relationships"):
        relationships = HeuristicExtractor.extract_relationships(text)
        if relationships:
            enhanced["relationships"] = relationships

    return enhanced
