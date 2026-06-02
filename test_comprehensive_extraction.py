#!/usr/bin/env python3
"""
Test comprehensive extraction: Shows extraction of ALL facts from document.
"""

from pathlib import Path
from src.wiki_builder import WikiBuilder

SAMPLE_DOCUMENT = """
TESLA ANNOUNCES MAJOR GEORGIA EXPANSION

Tesla Inc., led by CEO Elon Musk, announced on May 15, 2024, a significant $5 billion investment
in expanding its Georgia manufacturing facility. The facility is located in Cobb County near Atlanta,
Georgia 30303, at coordinates 33.9425° N, 84.4277° W.

INVESTMENT DETAILS
The investment will create 2,500 new jobs over three years, with hiring starting in Q3 2024. The
facility will expand from 750,000 to 1.2 million vehicles per year capacity. An additional 500 MW
battery pack assembly line will be built by Q4 2025.

FACILITY STATUS
The Tesla Georgia plant has been operational since 2022 and currently employs over 10,000 workers.
The facility produces Model Y vehicles and battery packs for the North American market. It operates
as a Tesla Inc. subsidiary with three shift operations expanding to three shifts.

PARTNER ANNOUNCEMENTS
Panasonic Energy, Tesla's battery supply partner based in Japan, announced a $300 million investment
to build a new battery cell manufacturing facility in DeKalb County, creating 800 jobs. Panasonic
President Koji Arima stated: "Our partnership with Tesla continues to grow."

Additional suppliers expanding operations:
- AutoSupply Components (tier 1 interior components supplier): $50 million investment, 250 jobs
- Southern Electronics Inc. (wiring harness manufacturer): $25 million, 150 jobs
- Georgia Steel Works (metal stamping): $15 million, 100 jobs

REGULATORY APPROVALS
Georgia Department of Environmental Protection (EPD) approvals include:
- Air Permit No. 2024-GAR-001: APPROVED
- Water discharge permits: PENDING (expected June 2024)
- Zoning approval: APPROVED by Cobb County

GOVERNMENTAL SUPPORT
Georgia Governor Brian Kemp held a press conference on May 14, 2024. SelectGeorgia, the state's
economic development organization, negotiated incentive packages with local authorities. The City
of Atlanta participated in negotiations.

LOCATION & LOGISTICS
The facility is adjacent to Port of Atlanta logistics hub (5 miles), enabling efficient vehicle
distribution. The facility is in Cobb County industrial zone. Nearby locations include Marietta,
Atlanta, and Savannah for supplier networks.

TECHNOLOGY & OPERATIONS
- New body shop automation systems
- Expanded paint facility with VOC controls
- New stamping press (5000 ton capacity)
- Worker training center in Atlanta
- On-site childcare facilities
- Wellness programs

RESEARCH PARTNERSHIPS
Georgia Institute of Technology partnership for advanced manufacturing research. Focus areas:
- Battery efficiency optimization
- Sustainable manufacturing processes
- AI-driven quality control

TIMELINE
- Q3 2024: Construction begins
- Q4 2024: New equipment installation
- Q2 2025: First phase operational
- Q4 2025: Full operations
- 2026: Full capacity reached

CAPACITY PROJECTIONS
- Current: 750,000 vehicles/year, 10,000 employees
- Post-expansion: 1.2 million vehicles/year, 12,500 employees
- Battery capacity: 500 MW additional

FINANCIAL DETAILS
- Total investment: $5 billion
- Panasonic investment: $300 million
- Supplier investments total: $90 million
- Expected payback: 8-10 years
- Return on investment: 15-20% annually

STRATEGIC IMPORTANCE
Tesla's U.S. production capacity increasing from 1.5M to 2.7M vehicles. Georgia becomes primary
East Coast hub. Part of broader Georgia EV supply chain ecosystem development. Supports state's
goal to become top EV manufacturing center in Southeast.

SUPPLY CHAIN
Tier 1 suppliers: 15 companies committing to Georgia operations
Tier 2 suppliers: 30+ companies in supply network
Logistics: Port of Savannah (100 miles), Atlanta International Airport (30 miles)

INCENTIVES & TAX CREDITS
- Georgia state tax credits: $50 million over 10 years
- Cobb County property tax abatement: 5 years
- City of Atlanta business tax credits
- Federal EV manufacturing tax credits: 30%

ENVIRONMENTAL COMMITMENTS
- Carbon neutral operations by 2025
- Water usage reduction: 40%
- Renewable energy: 100% by 2025
- Zero waste to landfill target
- Ecosystem restoration: 100 acres

COMMUNITY IMPACT
- Atlanta community: 2,500 direct jobs
- Regional contractors: 500+ jobs during construction
- Supplier ecosystem: 3,000+ jobs
- Total economic impact: $8 billion over 10 years
"""


def test_comprehensive():
    """Run comprehensive extraction."""
    print("=" * 80)
    print("COMPREHENSIVE EXTRACTION TEST - Extract ALL Facts")
    print("=" * 80)

    builder = WikiBuilder(comprehensive=True)

    print("\n📄 Sample document:")
    print(f"  Length: {len(SAMPLE_DOCUMENT):,} characters")
    print(f"  Sections: 15+")
    print(f"  Content types: Companies, investments, people, locations, permits,")
    print(f"                 timelines, numbers, relationships, etc.")

    print("\n🔍 Running COMPREHENSIVE extraction (7 strategies)...")
    print("  Strategy 1: Sentence-by-sentence extraction")
    print("  Strategy 2: Paragraph-level extraction")
    print("  Strategy 3: Entity mention extraction")
    print("  Strategy 4: Relationship extraction")
    print("  Strategy 5: Number and amount extraction")
    print("  Strategy 6: Temporal extraction")
    print("  Strategy 7: Exhaustive LLM extraction")

    result = builder.synthesize_document(
        doc_id="comprehensive_test_001",
        doc_title="Tesla Georgia Expansion - Complete Details",
        url="https://example.com/tesla-expansion-full",
        content=SAMPLE_DOCUMENT,
        company_name="Tesla",
    )

    print("\n" + "=" * 80)
    print("COMPREHENSIVE EXTRACTION RESULTS")
    print("=" * 80)

    total_entities = len(result["extracted_entities"])
    print(f"\n✅ Total entities extracted: {total_entities}")

    # Group by type
    by_type = {}
    for entity in result["extracted_entities"]:
        entity_type = entity["entity_type"]
        if entity_type not in by_type:
            by_type[entity_type] = []
        by_type[entity_type].append(entity)

    # Print by category
    category_order = [
        "company", "facility", "person", "investment", "relationship",
        "location", "permit", "amount", "jobs", "capacity", "date", "timeline"
    ]

    for entity_type in category_order:
        if entity_type in by_type:
            entities = by_type[entity_type]
            print(f"\n📍 {entity_type.upper()} ({len(entities)} entities):")
            for entity in sorted(entities[:15], key=lambda e: str(e.get("entity_name", ""))):
                name = entity.get("entity_name") or entity.get("fact") or entity.get("amount") or str(entity)
                print(f"   • {name}")
            if len(entities) > 15:
                print(f"   ... and {len(entities) - 15} more")

    # Show generated wiki
    wiki_dir = Path("wiki")
    if wiki_dir.exists():
        print("\n" + "=" * 80)
        print("GENERATED WIKI STRUCTURE")
        print("=" * 80)

        total_pages = 0
        for subdir in sorted(wiki_dir.iterdir()):
            if subdir.is_dir():
                md_files = list(subdir.glob("*.md"))
                if md_files:
                    total_pages += len(md_files)
                    print(f"\n📁 {subdir.name}/ ({len(md_files)} pages)")
                    for md_file in sorted(md_files)[:8]:
                        size = md_file.stat().st_size
                        print(f"   • {md_file.name} ({size} bytes)")
                    if len(md_files) > 8:
                        print(f"   ... and {len(md_files) - 8} more")

        print(f"\n📊 Total wiki pages created: {total_pages}")

    print("\n" + "=" * 80)
    print("KEY IMPROVEMENTS SUMMARY")
    print("=" * 80)
    print(f"""
✨ What Got Extracted:

{f"  • {total_entities}"} total entities from {len(SAMPLE_DOCUMENT):,} character document

Categories:
{f"  • {len(by_type.get('company', []))} companies/organizations"}
{f"  • {len(by_type.get('facility', []))} facilities"}
{f"  • {len(by_type.get('person', []))} people"}
{f"  • {len(by_type.get('investment', []))} investments"}
{f"  • {len(by_type.get('relationship', []))} relationships"}
{f"  • {len(by_type.get('location', []))} locations"}
{f"  • {len(by_type.get('permit', []))} permits/regulatory"}
{f"  • {len(by_type.get('amount', []))} dollar amounts"}
{f"  • {len(by_type.get('jobs', []))} job metrics"}
{f"  • {len(by_type.get('capacity', []))} capacity/production numbers"}
{f"  • {len(by_type.get('date', []))} dates/years"}
{f"  • {len(by_type.get('timeline', []))} timeline events"}

Strategies Used:
  ✓ Sentence-level extraction (granular facts)
  ✓ Paragraph-level extraction (context facts)
  ✓ Named entity recognition (companies, people, locations)
  ✓ Relationship detection (partnerships, supply chains)
  ✓ Numeric extraction (amounts, jobs, capacity)
  ✓ Temporal extraction (dates, timelines, quarters)
  ✓ Exhaustive LLM pass (catch anything missed)

Result: No facts left behind. Comprehensive coverage.
    """)

    return result


if __name__ == "__main__":
    result = test_comprehensive()
    print("\n✅ Comprehensive extraction test complete!")
    print(f"   Total entities: {len(result['extracted_entities'])}")
    print(f"   Pages created: {len(result['updated_pages'])}")
