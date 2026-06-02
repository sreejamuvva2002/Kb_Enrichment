"""
Comprehensive extraction - ensures NO facts are missed.
Uses aggressive multi-strategy extraction to capture everything.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

LOGGER = logging.getLogger(__name__)


class ComprehensiveExtractor:
    """
    Aggressive extraction strategy that ensures nothing is missed.
    Uses multiple strategies: keyword scanning, sentence analysis,
    entity recognition, and exhaustive LLM prompts.
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    def extract_everything(self, text: str, company_context: str | None = None) -> list[dict[str, Any]]:
        """
        Extract EVERYTHING from text using all available strategies.
        No filtering - return all detected facts.
        """
        all_facts = []

        # Strategy 1: Sentence-by-sentence extraction
        facts_by_sentence = self._extract_by_sentence(text, company_context)
        all_facts.extend(facts_by_sentence)
        LOGGER.info("Sentence extraction: %d facts", len(facts_by_sentence))

        # Strategy 2: Paragraph-level extraction
        facts_by_paragraph = self._extract_by_paragraph(text, company_context)
        all_facts.extend(facts_by_paragraph)
        LOGGER.info("Paragraph extraction: %d facts", len(facts_by_paragraph))

        # Strategy 3: Entity mention extraction (find all companies, locations, numbers)
        facts_by_entity = self._extract_all_entities(text)
        all_facts.extend(facts_by_entity)
        LOGGER.info("Entity extraction: %d facts", len(facts_by_entity))

        # Strategy 4: Relationship extraction (all connections)
        facts_by_relationship = self._extract_all_relationships(text)
        all_facts.extend(facts_by_relationship)
        LOGGER.info("Relationship extraction: %d facts", len(facts_by_relationship))

        # Strategy 5: Number and amount extraction
        facts_by_numbers = self._extract_all_numbers(text)
        all_facts.extend(facts_by_numbers)
        LOGGER.info("Number extraction: %d facts", len(facts_by_numbers))

        # Strategy 6: Temporal extraction (dates, timelines)
        facts_by_time = self._extract_temporal_facts(text)
        all_facts.extend(facts_by_time)
        LOGGER.info("Temporal extraction: %d facts", len(facts_by_time))

        # Strategy 7: Exhaustive LLM pass (final check for missed facts)
        facts_by_llm = self._exhaustive_llm_extraction(text, company_context)
        all_facts.extend(facts_by_llm)
        LOGGER.info("Exhaustive LLM extraction: %d facts", len(facts_by_llm))

        # Deduplicate facts
        unique_facts = self._deduplicate_facts(all_facts)
        LOGGER.info("After deduplication: %d unique facts from %d total", len(unique_facts), len(all_facts))

        return unique_facts

    def _extract_by_sentence(self, text: str, company_context: str | None = None) -> list[dict[str, Any]]:
        """
        Extract facts from each sentence individually.
        Ensures granular fact capture.
        """
        sentences = re.split(r'[.!?]+', text)
        facts = []

        for sent_idx, sentence in enumerate(sentences):
            sent = sentence.strip()
            if len(sent) < 10:
                continue

            # Skip if sentence is just a header or section title
            if len(sent.split()) < 5:
                continue

            prompt = f"""Extract EVERY fact mentioned in this single sentence. Return all facts, even small details.

Sentence: {sent[:800]}

Return ONLY a JSON array like:
[
  {{"fact": "specific detail mentioned", "type": "statement"}},
  {{"fact": "another detail", "type": "statement"}},
  {{"entity": "company name", "type": "company"}},
  {{"entity": "location name", "type": "location"}},
  {{"amount": "number or value", "type": "numeric"}}
]

Return ALL facts, including:
- Direct statements
- Company/facility names
- Locations and addresses
- Numbers and amounts
- Relationships
- Activities and actions
- Dates and timelines

JSON:"""

            result = self.llm.extract_facts(sent, prompt, max_tokens=400)
            if isinstance(result, list):
                for fact in result:
                    fact["source"] = f"sentence_{sent_idx}"
                    facts.extend([fact] if isinstance(fact, dict) else [])

        return facts

    def _extract_by_paragraph(self, text: str, company_context: str | None = None) -> list[dict[str, Any]]:
        """
        Extract facts from each paragraph.
        Captures broader context facts.
        """
        paragraphs = text.split('\n\n')
        facts = []

        for para_idx, paragraph in enumerate(paragraphs):
            para = paragraph.strip()
            if len(para) < 50:
                continue

            prompt = f"""Extract EVERY significant fact from this paragraph. List everything important.

PARAGRAPH:
{para[:1500]}

Return ONLY JSON array with ALL facts:
[
  {{"fact": "detail", "context": "related context"}},
  {{"entity": "name", "entity_type": "company/facility/person"}},
  {{"relationship": "A does X with B"}},
  {{"amount_or_number": "value with unit"}}
]

Include:
- All companies, facilities, people mentioned
- All numbers, amounts, percentages
- All locations
- All business activities
- All projects or plans
- All partnerships or relationships
- All achievements or milestones
- All problems or challenges mentioned
- All regulatory or legal mentions
- Timeline information

JSON:"""

            result = self.llm.extract_facts(para, prompt, max_tokens=600)
            if isinstance(result, list):
                for fact in result:
                    fact["source"] = f"paragraph_{para_idx}"
                    facts.extend([fact] if isinstance(fact, dict) else [])

        return facts

    def _extract_all_entities(self, text: str) -> list[dict[str, Any]]:
        """
        Extract ALL entity mentions: companies, facilities, people, locations, organizations.
        """
        facts = []

        # Company patterns
        company_patterns = [
            r'\b([A-Z][a-zA-Z\d\s&,.]*?)\s+(?:Inc|Corp|Ltd|LLC|Company|Co\.|Corporation|Industries|Energy|Manufacturing|Solutions|Systems|Group)',
            r'\b([A-Z][a-zA-Z\d&]*?)\s+(?:Technologies|Technology|Ventures|Capital|Partners|Enterprises)',
        ]

        for pattern in company_patterns:
            for match in re.finditer(pattern, text):
                company = match.group(1).strip()
                if len(company) > 2 and company.count(' ') < 5:
                    facts.append({
                        "entity_type": "company",
                        "entity_name": company,
                        "type": "company_mention",
                        "source": "regex_pattern"
                    })

        # Location patterns
        location_patterns = [
            r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:County|City|Township|Parish|District)',
            r'\b(?:Atlanta|Savannah|Augusta|Athens|Columbus|Macon|Marietta|Cobb|DeKalb|Fulton|Gwinnett)\b',
            r'\b(?:Georgia|GA|Georgia State)\b',
        ]

        for pattern in location_patterns:
            for match in re.finditer(pattern, text):
                location = match.group(0).strip()
                facts.append({
                    "entity_type": "location",
                    "entity_name": location,
                    "type": "location_mention",
                    "source": "regex_pattern"
                })

        # Person/Person names (CEO, Governor, etc.)
        person_patterns = [
            r'\b((?:Mr|Ms|Mrs|Dr|CEO|Governor|President|Director|Manager)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
            r'\b([A-Z][a-z]+\s+[A-Z][a-z]+\s+(?:announced|said|stated|commented))',
        ]

        for pattern in person_patterns:
            for match in re.finditer(pattern, text):
                person = match.group(1).strip()
                facts.append({
                    "entity_type": "person",
                    "entity_name": person,
                    "type": "person_mention",
                    "source": "regex_pattern"
                })

        return facts

    def _extract_all_relationships(self, text: str) -> list[dict[str, Any]]:
        """
        Extract ALL relationships: supplier, partner, parent, customer, etc.
        """
        facts = []

        relationship_keywords = [
            (r'(\w+)\s+(?:is|becomes|serves as|acts as)\s+(?:a|the)?\s*(supplier|customer|partner|competitor)', "relationship"),
            (r'(\w+)\s+(?:supplies|provides|sells|manufactures|produces)\s+(?:to|for)\s+(\w+)', "supplies"),
            (r'(\w+)\s+(?:partnered|partnering|partnership)\s+(?:with|to)\s+(\w+)', "partnership"),
            (r'(\w+)\s+(?:acquired|acquires|owns|subsidiary|parent)\s+(\w+)', "ownership"),
            (r'(\w+)\s+(?:and|with)\s+(\w+)\s+(?:collaborate|agreement|contract|deal)', "collaboration"),
        ]

        for pattern, rel_type in relationship_keywords:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entity_a = match.group(1)
                entity_b = match.group(2) if match.lastindex >= 2 else None

                if entity_b:
                    facts.append({
                        "entity_type": "relationship",
                        "company_a": entity_a,
                        "relationship_type": rel_type,
                        "company_b": entity_b,
                        "source": "regex_pattern"
                    })

        return facts

    def _extract_all_numbers(self, text: str) -> list[dict[str, Any]]:
        """
        Extract ALL numbers, amounts, percentages, metrics.
        """
        facts = []

        # Currency amounts
        currency_patterns = [
            (r'\$\s*(\d+(?:[.,]\d+)*)\s*(?:billion|million|thousand|B|M|K)?', "amount_usd"),
            (r'(\d+(?:[.,]\d+)*)\s*(?:billion|million|thousand)\s*(?:dollars|USD)?', "amount_value"),
        ]

        for pattern, amount_type in currency_patterns:
            for match in re.finditer(pattern, text):
                amount = match.group(0).strip()
                facts.append({
                    "entity_type": "amount",
                    "amount": amount,
                    "amount_type": amount_type,
                    "source": "regex_pattern"
                })

        # Job numbers
        job_patterns = [
            r'(\d+(?:,\d+)*)\s+(?:jobs|employees|workers|positions)',
            r'(?:create|hire|employ)\s+(\d+(?:,\d+)*)\s+(?:jobs|employees)',
        ]

        for pattern in job_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                jobs = match.group(1).replace(',', '')
                facts.append({
                    "entity_type": "jobs",
                    "jobs_count": int(jobs),
                    "context": match.group(0),
                    "source": "regex_pattern"
                })

        # Capacity/production numbers
        capacity_patterns = [
            r'(\d+(?:[.,]\d+)*)\s*(?:million|thousand)?\s*(?:vehicles|units|vehicles per year|capacity)',
            r'capacity.*?(\d+(?:[.,]\d+)*)\s*(?:million|thousand)?',
        ]

        for pattern in capacity_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                capacity = match.group(1)
                facts.append({
                    "entity_type": "capacity",
                    "value": capacity,
                    "context": match.group(0),
                    "source": "regex_pattern"
                })

        # Percentages
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*%', text):
            percentage = match.group(0)
            facts.append({
                "entity_type": "percentage",
                "value": percentage,
                "source": "regex_pattern"
            })

        return facts

    def _extract_temporal_facts(self, text: str) -> list[dict[str, Any]]:
        """
        Extract ALL temporal information: dates, timelines, timeframes.
        """
        facts = []

        # Year mentions
        for match in re.finditer(r'\b(19|20)\d{2}\b', text):
            year = match.group(0)
            facts.append({
                "entity_type": "date",
                "year": year,
                "source": "regex_pattern"
            })

        # Quarter mentions
        for match in re.finditer(r'\b(Q[1-4])\s+([12]\d{3})\b', text, re.IGNORECASE):
            quarter = match.group(1)
            year = match.group(2)
            facts.append({
                "entity_type": "date",
                "quarter": quarter,
                "year": year,
                "source": "regex_pattern"
            })

        # Month-Year mentions
        month_pattern = r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b'
        for match in re.finditer(month_pattern, text, re.IGNORECASE):
            month = match.group(1)
            year = match.group(2)
            facts.append({
                "entity_type": "date",
                "month": month,
                "year": year,
                "source": "regex_pattern"
            })

        # Timeline expressions
        timeline_patterns = [
            r'(?:by|through|until|before)\s+([12]\d{3})',
            r'(?:in the next|over the next|within)\s+(\d+)\s+(?:years|months|weeks|days)',
            r'(?:starting|beginning|launching)\s+(?:in|by)\s+([12]\d{3})',
        ]

        for pattern in timeline_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                timeline = match.group(0)
                facts.append({
                    "entity_type": "timeline",
                    "description": timeline,
                    "source": "regex_pattern"
                })

        return facts

    def _exhaustive_llm_extraction(self, text: str, company_context: str | None = None) -> list[dict[str, Any]]:
        """
        Final exhaustive pass: ask LLM to list EVERYTHING it can find.
        This catches facts that other strategies might miss.
        """
        company_hint = f"Context: This document is about {company_context}.\n" if company_context else ""

        prompt = f"""{company_hint}Your task: Extract EVERY single fact, detail, number, name, and relationship mentioned in this text.

Do NOT filter or summarize. Return EVERYTHING.

Include:
- Every company, facility, or organization name
- Every person name and title
- Every location (city, county, country)
- Every number, amount, or metric
- Every date or time reference
- Every product or service mentioned
- Every business relationship
- Every event or announcement
- Every problem or challenge mentioned
- Every achievement or milestone
- Every regulatory or legal detail
- Every contact information
- Every capability or feature mentioned
- Every partnership or agreement
- Every investment or financial detail
- Every expansion or change planned
- Any other specific information mentioned

TEXT:
{text[:2500]}

Return ONLY a comprehensive JSON array with ALL facts discovered:
[
  {{"fact": "exact detail mentioned", "category": "statement"}},
  {{"entity": "name", "entity_type": "company/person/location/organization"}},
  {{"number": "123456", "description": "what this number represents"}},
  {{"relationship": "Entity A does X with Entity B"}},
  {{"timeline": "when something happens", "year": "2024"}},
  ...
]

Be exhaustive. Do not leave anything out. Include even minor details.

JSON:"""

        result = self.llm.extract_facts(text, prompt, max_tokens=1500)

        facts = []
        if isinstance(result, list):
            for fact in result:
                if isinstance(fact, dict):
                    fact["source"] = "exhaustive_llm"
                    facts.append(fact)

        return facts

    def _deduplicate_facts(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Remove duplicate facts while preserving all unique information.
        """
        seen = {}
        unique = []

        for fact in facts:
            # Create a hashable key from the fact
            if "entity_name" in fact:
                key = f"{fact.get('entity_type', 'unknown')}:{fact['entity_name']}"
            elif "fact" in fact:
                key = f"fact:{fact['fact']}"
            elif "amount" in fact:
                key = f"amount:{fact['amount']}"
            elif "company_a" in fact and "company_b" in fact:
                key = f"rel:{fact['company_a']}:{fact.get('relationship_type', 'unknown')}:{fact['company_b']}"
            else:
                key = str(fact)

            if key not in seen:
                seen[key] = True
                unique.append(fact)

        return unique
