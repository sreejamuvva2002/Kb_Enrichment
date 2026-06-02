"""
LLM Wiki Builder - Synthesizes downloaded documents into persistent markdown knowledge base.
Uses local LLM (via Ollama/similar) for incremental fact extraction and wiki updates.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from datetime import datetime

from src import CONFIG_DIR, REPO_ROOT, iso_now
from src.comprehensive_extractor import ComprehensiveExtractor

LOGGER = logging.getLogger(__name__)
WIKI_DIR = REPO_ROOT / "wiki"


def load_wiki_schema() -> dict[str, Any]:
    """Load wiki schema defining what entities and facts to extract."""
    schema_path = CONFIG_DIR / "wiki_schema.json"
    if not schema_path.exists():
        return {}
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


class LocalLLMClient:
    """Interface to local LLM (Ollama, LM Studio, etc.)"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "mistral"):
        self.base_url = base_url
        self.model = model
        self._client = None

    def get_client(self):
        """Lazy-load ollama client."""
        if self._client is None:
            import ollama
            self._client = ollama
        return self._client

    def extract_facts(self, text: str, extraction_prompt: str, max_tokens: int = 500) -> dict[str, Any]:
        """
        Extract structured facts from text using local LLM.
        Returns JSON-compatible dict parsed from response.
        """
        client = self.get_client()
        try:
            response = client.generate(
                model=self.model,
                prompt=extraction_prompt,
                stream=False,
                options={
                    "num_ctx": 2048,
                    "top_k": 40,
                    "top_p": 0.9,
                    "temperature": 0.3,  # Lower temp for consistent extraction
                },
            )
            text_response = response.get("response", "").strip()
            # Try to extract JSON from response
            json_match = re.search(r"\{.*\}", text_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {}
        except Exception as exc:
            LOGGER.warning("LLM extraction failed: %s", exc)
            return {}

    def summarize(self, text: str, max_tokens: int = 150) -> str:
        """Summarize text in 1-2 sentences."""
        client = self.get_client()
        prompt = f"""Summarize the following in 1-2 sentences for a knowledge base:

{text[:1000]}

Summary:"""
        try:
            response = client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
                options={"num_ctx": 1024, "temperature": 0.3},
            )
            return response.get("response", "").strip()
        except Exception as exc:
            LOGGER.warning("Summarization failed: %s", exc)
            return ""


class TextChunker:
    """Break documents into extraction-friendly chunks."""

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
        """
        Split text into overlapping chunks for extraction.
        Aims for ~800 tokens per chunk (rough estimate: 1 token ≈ 4 chars).
        """
        char_size = chunk_size * 4
        overlap_char = overlap * 4
        chunks = []
        pos = 0
        while pos < len(text):
            chunk = text[pos : pos + char_size]
            chunks.append(chunk)
            pos += char_size - overlap_char
        return [c for c in chunks if c.strip()]


class WikiPage:
    """Represents a single wiki markdown page."""

    def __init__(self, path: Path):
        self.path = path
        self.title = path.stem
        self.content = self._load()

    def _load(self) -> str:
        if self.path.exists():
            return self.path.read_text(encoding="utf-8")
        return ""

    def save(self) -> None:
        """Write page to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.content, encoding="utf-8")

    def add_section(self, section_name: str, content: str, merge: bool = True) -> None:
        """Add or update a section in the page."""
        section_marker = f"## {section_name}"
        if section_marker in self.content and merge:
            # Replace existing section
            parts = self.content.split(section_marker)
            if len(parts) > 1:
                before = parts[0]
                after_parts = parts[1].split("## ")
                after = ("## ".join(after_parts[1:])) if len(after_parts) > 1 else ""
                self.content = f"{before}{section_marker}\n{content}\n\n{after}"
            else:
                self.content += f"\n{section_marker}\n{content}\n"
        else:
            self.content += f"\n{section_marker}\n{content}\n"

    def link_document(self, doc_id: str, doc_title: str, url: str) -> None:
        """Add document source link."""
        if "## Sources" not in self.content:
            self.add_section("Sources", "")
        doc_link = f"- [{doc_title}]({url}) (doc_id: {doc_id})"
        if doc_link not in self.content:
            sources_idx = self.content.find("## Sources")
            if sources_idx >= 0:
                end_idx = self.content.find("\n## ", sources_idx + 1)
                if end_idx < 0:
                    end_idx = len(self.content)
                section_content = self.content[sources_idx : end_idx]
                if doc_link not in section_content:
                    self.content = (
                        self.content[:end_idx] + f"{doc_link}\n" + self.content[end_idx :]
                    )


class WikiBuilder:
    """Main wiki synthesis orchestrator."""

    def __init__(
        self,
        wiki_dir: Path = WIKI_DIR,
        llm_base_url: str = "http://localhost:11434",
        llm_model: str = "mistral",
        comprehensive: bool = True,
    ):
        self.wiki_dir = Path(wiki_dir)
        self.llm = LocalLLMClient(llm_base_url, llm_model)
        self.schema = load_wiki_schema()
        self.chunker = TextChunker()
        self.comprehensive = comprehensive
        if comprehensive:
            self.comprehensive_extractor = ComprehensiveExtractor(self.llm)

    def synthesize_document(
        self,
        doc_id: str,
        doc_title: str,
        url: str,
        content: str,
        company_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Extract entities and facts from a single document.
        Updates relevant wiki pages.
        """
        if not content or len(content) < 200:
            return {"doc_id": doc_id, "status": "skipped", "reason": "content_too_short"}

        results = {
            "doc_id": doc_id,
            "doc_title": doc_title,
            "url": url,
            "company_name": company_name,
            "extracted_entities": [],
            "updated_pages": [],
            "processed_at": iso_now(),
        }

        chunks = self.chunker.chunk_text(content)
        all_facts = []

        # Extract facts from each chunk
        for chunk_idx, chunk in enumerate(chunks):
            facts = self._extract_chunk_facts(chunk, company_name)
            if facts:
                all_facts.extend(facts)
                LOGGER.info(
                    "Extracted %s facts from chunk %s of doc %s",
                    len(facts),
                    chunk_idx + 1,
                    doc_id,
                )

        LOGGER.info("Total facts extracted from doc %s: %s", doc_id, len(all_facts))

        # Smart deduplication by entity type + key fields
        entity_facts = self._deduplicate_facts(all_facts)

        LOGGER.info("After deduplication: %s unique entities", len(entity_facts))

        # Update wiki pages for each entity
        for entity_key, fact in entity_facts.items():
            pages_updated = self._update_entity_pages(fact, doc_id, doc_title, url)
            results["updated_pages"].extend(pages_updated)
            results["extracted_entities"].append(
                {
                    "entity_type": fact.get("entity_type"),
                    "entity_name": fact.get("entity_name"),
                    "pages_updated": pages_updated,
                }
            )

        return results

    def _deduplicate_facts(self, facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """
        Smart deduplication: merge similar facts based on entity type and key identifiers.
        Handles cases where the same entity appears in multiple extractions.
        """
        entity_facts = {}

        for fact in facts:
            entity_type = fact.get("entity_type", "unknown")
            entity_name = fact.get("entity_name", "")

            # Create a dedup key based on type and name
            if entity_type == "company":
                key = f"company:{self._normalize_name(entity_name)}"
            elif entity_type == "facility":
                key = f"facility:{self._normalize_name(entity_name)}"
            elif entity_type == "investment":
                key = f"investment:{self._normalize_name(entity_name)}"
            elif entity_type == "relationship":
                # For relationships, key by both companies
                a = self._normalize_name(fact.get("company_a", ""))
                b = self._normalize_name(fact.get("company_b", ""))
                rel_type = fact.get("relationship_type", "")
                key = f"relationship:{a}:{rel_type}:{b}"
            else:
                key = f"{entity_type}:{self._normalize_name(entity_name)}"

            if key not in entity_facts:
                entity_facts[key] = fact
            else:
                # Merge: collect all facts from both occurrences
                existing = entity_facts[key]
                merged = dict(existing)

                # Merge facts lists
                existing_facts = set(existing.get("facts", []))
                new_facts = set(fact.get("facts", []))
                merged["facts"] = list(existing_facts | new_facts)

                # Take non-empty fields from new fact
                for field in ["location", "facility_type", "products", "company_type", "details", "amount", "jobs", "date"]:
                    if fact.get(field) and not existing.get(field):
                        merged[field] = fact[field]

                entity_facts[key] = merged

        return entity_facts

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize names for comparison: lowercase, remove extra spaces."""
        return " ".join(name.lower().strip().split())

    def _extract_chunk_facts(self, chunk: str, company_context: str | None = None) -> list[dict[str, Any]]:
        """Extract entities and facts from a single chunk using LLM."""
        all_facts = []

        if self.comprehensive:
            # Use exhaustive extraction strategy
            all_facts = self.comprehensive_extractor.extract_everything(chunk, company_context)
        else:
            # Use multi-pass extraction for comprehensive coverage
            extraction_passes = [
                self._extract_companies_and_facilities(chunk, company_context),
                self._extract_investments_and_jobs(chunk),
                self._extract_relationships(chunk),
                self._extract_regulatory_and_permits(chunk),
                self._extract_locations_and_addresses(chunk),
            ]

            for facts in extraction_passes:
                all_facts.extend(facts)

        return all_facts

    def _extract_companies_and_facilities(self, chunk: str, company_context: str | None = None) -> list[dict[str, Any]]:
        """Extract company and facility entities."""
        company_hint = f"Primary company: {company_context}\n" if company_context else ""
        prompt = f"""{company_hint}Extract ALL companies and facilities mentioned in this text.

Include EVERY company name mentioned, even briefly.
Include facility names, plant names, locations.

For each entity, provide:
- Full name
- What type (manufacturer, supplier, OEM, battery company, etc.)
- Where located (city, county, state)
- What they do (products, services, role in supply chain)
- Relationships to other companies mentioned

TEXT:
{chunk[:2000]}

Return ONLY a JSON array like:
[
  {{"entity_type": "company", "entity_name": "Tesla", "company_type": "OEM", "location": "Fremont, California", "georgia_operations": "Atlanta plant", "products": "Electric vehicles, batteries", "facts": ["manufactures EVs", "has Georgia facility"]}},
  {{"entity_type": "facility", "entity_name": "Tesla Georgia Plant", "owner": "Tesla", "location": "Cobb County, Georgia", "facility_type": "Manufacturing", "products": "Vehicle assembly, battery packs", "facts": ["operational since 2022", "employs 10000+"]}},
  {{"entity_type": "company", "entity_name": "Panasonic", "company_type": "Supplier", "location": "Japan", "georgia_operations": "Battery manufacturing Georgia", "products": "Battery cells and packs", "facts": []}}
]

JSON:"""
        result = self.llm.extract_facts(chunk, prompt, max_tokens=800)
        if isinstance(result, list):
            return result
        return []

    def _extract_investments_and_jobs(self, chunk: str) -> list[dict[str, Any]]:
        """Extract investment amounts, job creation, expansions."""
        prompt = f"""Extract ALL investment announcements, job creation, and expansion plans.

Look for:
- Investment amounts (any currency, any magnitude)
- Job creation numbers
- Facility expansions
- Capacity increases
- New plant announcements
- Project timelines

For each, provide amount, location, company involved, and date if mentioned.

TEXT:
{chunk[:2000]}

Return ONLY a JSON array like:
[
  {{"entity_type": "investment", "entity_name": "Tesla Georgia Expansion 2024", "company": "Tesla", "amount": "$5 billion", "jobs": 2500, "location": "Georgia", "facility": "Atlanta plant", "details": "Expansion of battery production capacity", "announced_date": "2024", "facts": ["creates jobs", "increases capacity"]}},
  {{"entity_type": "investment", "entity_name": "Battery Supplier Expansion", "company": "Panasonic", "amount": "$500 million", "jobs": 800, "location": "Georgia", "facility": "New facility", "details": "Battery cell manufacturing", "announced_date": "2024", "facts": []}}
]

JSON:"""
        result = self.llm.extract_facts(chunk, prompt, max_tokens=800)
        if isinstance(result, list):
            return result
        return []

    def _extract_relationships(self, chunk: str) -> list[dict[str, Any]]:
        """Extract business relationships and supply chain connections."""
        prompt = f"""Extract ALL business relationships and supply chain connections mentioned.

Look for:
- Supplier relationships (who supplies whom)
- Customer relationships
- Partnerships and collaborations
- Parent company / subsidiary relationships
- Joint ventures
- Acquisitions or ownership changes
- OEM-supplier connections

For each relationship, identify:
- Company A name
- Relationship type (supplier_of, partner_with, subsidiary_of, etc)
- Company B name
- Details/products involved

TEXT:
{chunk[:2000]}

Return ONLY a JSON array like:
[
  {{"entity_type": "relationship", "company_a": "Tesla", "relationship_type": "customer_of", "company_b": "Panasonic", "details": "Battery supply agreement", "products": "Battery packs for vehicles"}},
  {{"entity_type": "relationship", "company_a": "Local Supplier Co", "relationship_type": "supplier_of", "company_b": "Tesla", "details": "Component supplier", "products": "Automotive components"}},
  {{"entity_type": "relationship", "company_a": "Tesla Georgia", "relationship_type": "subsidiary_of", "company_b": "Tesla Inc", "details": "Operations in Georgia", "products": "Vehicle assembly"}}
]

JSON:"""
        result = self.llm.extract_facts(chunk, prompt, max_tokens=800)
        if isinstance(result, list):
            return result
        return []

    def _extract_regulatory_and_permits(self, chunk: str) -> list[dict[str, Any]]:
        """Extract permits, regulatory approvals, certifications."""
        prompt = f"""Extract ALL mentions of permits, regulatory approvals, and environmental information.

Look for:
- Environmental permits (air permit, water permit, EPD)
- Regulatory approvals
- Certifications and standards
- Regulatory bodies and agencies
- Compliance information
- Zoning or land use approvals
- Environmental impact assessments

For each, provide:
- Permit/approval type
- Facility involved
- Issuing agency
- Date if mentioned
- Status (approved, pending, etc)

TEXT:
{chunk[:2000]}

Return ONLY a JSON array like:
[
  {{"entity_type": "permit", "permit_type": "Air Permit", "facility": "Tesla Georgia Plant", "issuing_agency": "Georgia EPD", "location": "Cobb County, Georgia", "date": "2022", "status": "Active"}},
  {{"entity_type": "regulatory", "approval_type": "Environmental Compliance", "facility": "Battery Manufacturing Plant", "agency": "EPA", "details": "Battery manufacturing standards met", "facts": []}}
]

JSON:"""
        result = self.llm.extract_facts(chunk, prompt, max_tokens=600)
        if isinstance(result, list):
            return result
        return []

    def _extract_locations_and_addresses(self, chunk: str) -> list[dict[str, Any]]:
        """Extract specific locations, addresses, geographic details."""
        prompt = f"""Extract ALL specific geographic locations and addresses mentioned.

Look for:
- Cities and counties in Georgia
- Specific addresses or addresses
- Regional areas
- Industrial parks or developments
- Counties with investments
- Facilities in specific locations

For each location, provide:
- Location name (city/county/address)
- State
- What facility or company is there
- What activity happens there

TEXT:
{chunk[:2000]}

Return ONLY a JSON array like:
[
  {{"entity_type": "location", "location_name": "Cobb County", "state": "Georgia", "facility": "Tesla Georgia Plant", "details": "Major manufacturing facility", "facts": ["EV assembly", "battery production"]}},
  {{"entity_type": "location", "location_name": "Atlanta", "state": "Georgia", "facility": "Tesla headquarters Georgia", "details": "Regional operations center", "facts": []}}
]

JSON:"""
        result = self.llm.extract_facts(chunk, prompt, max_tokens=600)
        if isinstance(result, list):
            return result
        return []

    def _update_entity_pages(
        self, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> list[str]:
        """Update wiki pages for an extracted entity."""
        entity_type = fact.get("entity_type", "unknown")
        entity_name = fact.get("entity_name", "Unknown")
        pages_updated = []

        # Route to appropriate wiki section based on entity type
        if entity_type == "company":
            page_path = self.wiki_dir / "companies" / f"{self._slugify(entity_name)}.md"
            pages_updated.append(self._update_company_page(page_path, entity_name, fact, doc_id, doc_title, url))
        elif entity_type == "facility":
            page_path = self.wiki_dir / "facilities" / f"{self._slugify(entity_name)}.md"
            pages_updated.append(self._update_facility_page(page_path, entity_name, fact, doc_id, doc_title, url))
        elif entity_type == "investment":
            page_path = self.wiki_dir / "investments" / f"{self._slugify(entity_name)}.md"
            pages_updated.append(self._update_investment_page(page_path, entity_name, fact, doc_id, doc_title, url))
        elif entity_type == "relationship":
            page_path = self.wiki_dir / "relationships" / f"{self._slugify(entity_name)}.md"
            pages_updated.append(self._update_relationship_page(page_path, entity_name, fact, doc_id, doc_title, url))
        elif entity_type == "permit":
            page_path = self.wiki_dir / "permits" / f"{self._slugify(entity_name)}.md"
            pages_updated.append(self._update_permit_page(page_path, entity_name, fact, doc_id, doc_title, url))
        elif entity_type == "location":
            page_path = self.wiki_dir / "locations" / f"{self._slugify(entity_name)}.md"
            pages_updated.append(self._update_location_page(page_path, entity_name, fact, doc_id, doc_title, url))
        elif entity_type == "regulatory":
            page_path = self.wiki_dir / "regulatory" / f"{self._slugify(entity_name)}.md"
            pages_updated.append(self._update_regulatory_page(page_path, entity_name, fact, doc_id, doc_title, url))
        elif entity_type == "person":
            page_path = self.wiki_dir / "people" / f"{self._slugify(entity_name)}.md"
            pages_updated.append(self._update_person_page(page_path, entity_name, fact, doc_id, doc_title, url))
        elif entity_type in ["amount", "jobs", "capacity", "percentage"]:
            # These are tracked in supporting pages, not standalone
            pass
        elif entity_type == "date" or entity_type == "timeline":
            # Dates are tracked in timeline pages
            pass
        elif entity_type == "fact" or "fact" in fact:
            # Generic fact, add to facts log
            page_path = self.wiki_dir / "facts_log" / f"facts_{doc_id}.md"
            pages_updated.append(self._append_fact_to_log(page_path, fact, doc_id, doc_title, url))

        return pages_updated

    def _update_company_page(
        self, page_path: Path, company_name: str, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Update or create company profile page."""
        page = WikiPage(page_path)

        # Initialize page if new
        if not page.content:
            page.content = f"# {company_name}\n\n"

        # Overview section
        if fact.get("company_type") and "Overview" not in page.content:
            overview = f"{company_name} is a {fact.get('company_type', 'company')}."
            page.add_section("Overview", overview)

        # Key Facts
        if fact.get("facts"):
            facts_text = "\n".join(f"- {f}" for f in fact.get("facts", []))
            page.add_section("Key Facts", facts_text)

        # Location / Geography
        if fact.get("location"):
            page.add_section("Headquarters", fact["location"])

        if fact.get("georgia_operations"):
            page.add_section("Georgia Operations", fact["georgia_operations"])

        # Products and Services
        if fact.get("products"):
            page.add_section("Products & Services", fact["products"])

        # Document source
        page.link_document(doc_id, doc_title, url)
        page.save()
        return page_path.name

    def _update_facility_page(
        self, page_path: Path, facility_name: str, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Update or create facility page."""
        page = WikiPage(page_path)

        if not page.content:
            page.content = f"# {facility_name}\n\n"

        # Owner company
        if fact.get("owner"):
            page.add_section("Owner Company", fact["owner"])

        # Location details
        if fact.get("location"):
            page.add_section("Location", fact["location"])

        # Facility type
        if fact.get("facility_type"):
            page.add_section("Facility Type", fact["facility_type"])

        # Products produced
        if fact.get("products"):
            page.add_section("Products & Output", fact["products"])

        # Capacity
        if fact.get("capacity"):
            page.add_section("Capacity", fact["capacity"])

        # Key facts
        if fact.get("facts"):
            facts_text = "\n".join(f"- {f}" for f in fact.get("facts", []))
            page.add_section("Key Information", facts_text)

        page.link_document(doc_id, doc_title, url)
        page.save()
        return page_path.name

    def _update_investment_page(
        self, page_path: Path, investment_name: str, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Update or create investment/announcement page."""
        page = WikiPage(page_path)

        if not page.content:
            page.content = f"# {investment_name}\n\n"

        # Overview with company
        if fact.get("company") and "Overview" not in page.content:
            overview = f"Investment by {fact.get('company')} announced in {fact.get('announced_date', 'unknown year')}"
            page.add_section("Overview", overview)

        # Investment amount
        if fact.get("amount"):
            page.add_section("Investment Amount", fact["amount"])

        # Jobs created
        if fact.get("jobs"):
            page.add_section("Jobs Created", str(fact["jobs"]))

        # Location
        if fact.get("location"):
            page.add_section("Location", fact["location"])

        # Facility involved
        if fact.get("facility"):
            page.add_section("Facility", fact["facility"])

        # Announcement date
        if fact.get("announced_date"):
            page.add_section("Announced", fact["announced_date"])

        # Details/description
        if fact.get("details"):
            page.add_section("Project Details", fact["details"])

        # Key facts
        if fact.get("facts"):
            facts_text = "\n".join(f"- {f}" for f in fact.get("facts", []))
            page.add_section("Additional Information", facts_text)

        page.link_document(doc_id, doc_title, url)
        page.save()
        return page_path.name

    def _update_relationship_page(
        self, page_path: Path, relationship_name: str, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Update or create supply chain relationship page."""
        page = WikiPage(page_path)

        if not page.content:
            page.content = f"# {relationship_name}\n\n"

        # Overview
        company_a = fact.get("company_a", "Company A")
        company_b = fact.get("company_b", "Company B")
        rel_type = fact.get("relationship_type", "related to")
        overview = f"{company_a} is {rel_type} {company_b}"
        if "Overview" not in page.content:
            page.add_section("Overview", overview)

        # Companies involved
        companies = f"- {company_a}\n- {company_b}"
        page.add_section("Companies", companies)

        # Relationship type
        if fact.get("relationship_type"):
            page.add_section("Relationship Type", fact["relationship_type"])

        # Details
        if fact.get("details"):
            page.add_section("Details", fact["details"])

        # Products involved
        if fact.get("products"):
            page.add_section("Products", fact["products"])

        page.link_document(doc_id, doc_title, url)
        page.save()
        return page_path.name

    def _update_permit_page(
        self, page_path: Path, permit_name: str, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Update or create permit/approval page."""
        page = WikiPage(page_path)

        if not page.content:
            page.content = f"# {permit_name}\n\n"

        # Permit type
        if fact.get("permit_type"):
            page.add_section("Permit Type", fact["permit_type"])

        # Facility
        if fact.get("facility"):
            page.add_section("Facility", fact["facility"])

        # Location
        if fact.get("location"):
            page.add_section("Location", fact["location"])

        # Issuing agency
        if fact.get("issuing_agency"):
            page.add_section("Issuing Agency", fact["issuing_agency"])

        # Status
        if fact.get("status"):
            page.add_section("Status", fact["status"])

        # Date
        if fact.get("date"):
            page.add_section("Date Issued", fact["date"])

        page.link_document(doc_id, doc_title, url)
        page.save()
        return page_path.name

    def _update_location_page(
        self, page_path: Path, location_name: str, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Update or create geographic location page."""
        page = WikiPage(page_path)

        if not page.content:
            page.content = f"# {location_name}\n\n"

        # State
        if fact.get("state"):
            page.add_section("State", fact["state"])

        # Facility info
        if fact.get("facility"):
            page.add_section("Major Facility", fact["facility"])

        # Activity
        if fact.get("details"):
            page.add_section("Economic Activity", fact["details"])

        # Key facts
        if fact.get("facts"):
            facts_text = "\n".join(f"- {f}" for f in fact.get("facts", []))
            page.add_section("Information", facts_text)

        page.link_document(doc_id, doc_title, url)
        page.save()
        return page_path.name

    def _update_regulatory_page(
        self, page_path: Path, regulatory_name: str, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Update or create regulatory/compliance page."""
        page = WikiPage(page_path)

        if not page.content:
            page.content = f"# {regulatory_name}\n\n"

        # Approval type
        if fact.get("approval_type"):
            page.add_section("Approval Type", fact["approval_type"])

        # Facility
        if fact.get("facility"):
            page.add_section("Facility", fact["facility"])

        # Agency
        if fact.get("agency"):
            page.add_section("Responsible Agency", fact["agency"])

        # Details
        if fact.get("details"):
            page.add_section("Details", fact["details"])

        page.link_document(doc_id, doc_title, url)
        page.save()
        return page_path.name

    def _update_person_page(
        self, page_path: Path, person_name: str, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Update or create person profile page."""
        page = WikiPage(page_path)

        if not page.content:
            page.content = f"# {person_name}\n\n"

        # Title/role
        if fact.get("title"):
            page.add_section("Title", fact["title"])

        # Organization
        if fact.get("organization"):
            page.add_section("Organization", fact["organization"])

        # Activities
        if fact.get("facts"):
            facts_text = "\n".join(f"- {f}" for f in fact.get("facts", []))
            page.add_section("Activities & Statements", facts_text)

        page.link_document(doc_id, doc_title, url)
        page.save()
        return page_path.name

    def _append_fact_to_log(
        self, page_path: Path, fact: dict[str, Any], doc_id: str, doc_title: str, url: str
    ) -> str:
        """Append a fact to the document's fact log."""
        page_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize if new
        if not page_path.exists():
            content = f"# Facts from {doc_title}\n\n"
            page_path.write_text(content, encoding="utf-8")

        content = page_path.read_text(encoding="utf-8")

        # Add fact entry
        fact_text = json.dumps(fact, indent=2)
        if "## Facts" not in content:
            content += "\n## Facts\n"
            content += f"```json\n{fact_text}\n```\n\n"
        else:
            # Append to existing facts section
            content = content.replace("## Facts\n", f"## Facts\n```json\n{fact_text}\n```\n\n")

        # Ensure source link
        if f"Source: [{doc_title}]({url})" not in content:
            content += f"\nSource: [{doc_title}]({url})\n"

        page_path.write_text(content, encoding="utf-8")
        return page_path.name

    @staticmethod
    def _slugify(name: str) -> str:
        """Convert name to filename-safe slug."""
        slug = name.lower().replace(" ", "_").replace("-", "_")
        slug = re.sub(r"[^a-z0-9_]", "", slug)
        return slug[:50]


def synthesize_batch(
    documents: list[dict[str, Any]],
    wiki_dir: Path = WIKI_DIR,
    llm_model: str = "mistral",
) -> dict[str, Any]:
    """
    Synthesize a batch of downloaded documents into wiki.

    Args:
        documents: List of dicts with keys: doc_id, doc_title, url, content, company_name
        wiki_dir: Path to wiki root directory
        llm_model: Local LLM model name (default: mistral)

    Returns:
        Batch results including entity count, pages updated, etc.
    """
    builder = WikiBuilder(wiki_dir=wiki_dir, llm_model=llm_model)
    batch_results = {
        "total_documents": len(documents),
        "processed": 0,
        "skipped": 0,
        "total_entities": 0,
        "pages_updated": 0,
        "document_results": [],
    }

    for doc in documents:
        if not doc.get("content"):
            batch_results["skipped"] += 1
            continue

        result = builder.synthesize_document(
            doc_id=doc["doc_id"],
            doc_title=doc.get("doc_title", "Untitled"),
            url=doc["url"],
            content=doc["content"],
            company_name=doc.get("company_name"),
        )

        batch_results["document_results"].append(result)
        batch_results["processed"] += 1
        batch_results["total_entities"] += len(result.get("extracted_entities", []))
        batch_results["pages_updated"] += len(result.get("updated_pages", []))

        LOGGER.info(
            "Synthesized doc %s: extracted %s entities, updated %s pages",
            doc["doc_id"],
            len(result.get("extracted_entities", [])),
            len(result.get("updated_pages", [])),
        )

    return batch_results
