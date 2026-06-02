#!/usr/bin/env python3
"""
Example: Using the Wiki Builder standalone to synthesize documents.

Run: python examples/wiki_example.py
"""

from pathlib import Path
from src.wiki_builder import WikiBuilder, TextChunker
from src.wiki_extractors import HeuristicExtractor, fill_facts_with_heuristics

# Sample document about an EV company investment
SAMPLE_DOC = """
Tesla announced a $5 billion expansion of its manufacturing facility in Atlanta, Georgia.
The investment will create 2,500 new jobs in Cobb County and support battery production.

The Atlanta facility, located in the Cobb County industrial area, will expand capacity
to 1 million vehicles per year. This follows Tesla's successful ramp of Model Y production
since the facility opened in 2022.

The facility currently employs over 10,000 workers and produces battery packs for
electric vehicles. The expansion is part of Tesla's broader Georgia growth strategy,
which also includes supplier partnerships with local component manufacturers.

Panasonic and other suppliers have already announced plans to expand their presence
in Georgia to support Tesla's growth. The investment requires several new environmental
permits from the Georgia EPD.

The announcement was made during a press conference attended by Georgia Governor
Brian Kemp and local economic development officials. SelectGeorgia highlighted the
investment as part of the state's growing EV supply chain ecosystem.
"""


def example_basic_extraction():
    """Example 1: Basic LLM-based extraction."""
    print("=" * 60)
    print("Example 1: Basic LLM Extraction")
    print("=" * 60)

    builder = WikiBuilder()
    chunker = TextChunker()

    # Break document into chunks
    chunks = chunker.chunk_text(SAMPLE_DOC, chunk_size=500, overlap=50)
    print(f"\nDocument split into {len(chunks)} chunks\n")

    # Extract facts from first chunk
    if chunks:
        print(f"Chunk 1 ({len(chunks[0])} chars):")
        print(f"{chunks[0][:200]}...\n")

        facts = builder._extract_chunk_facts(chunks[0], company_context="Tesla")
        print(f"Extracted {len(facts)} facts")
        for fact in facts:
            print(f"  - {fact.get('entity_type')}: {fact.get('entity_name')}")


def example_heuristic_extraction():
    """Example 2: Fallback heuristic extraction."""
    print("\n" + "=" * 60)
    print("Example 2: Heuristic Extraction (no LLM needed)")
    print("=" * 60)

    # Extract amounts
    amounts = HeuristicExtractor.extract_amounts(SAMPLE_DOC)
    print(f"\nExtracted {len(amounts)} amounts:")
    for amount in amounts:
        print(f"  - {amount['value']}")

    # Extract dates
    dates = HeuristicExtractor.extract_dates(SAMPLE_DOC)
    print(f"\nExtracted {len(dates)} dates: {dates}")

    # Extract locations
    locations = HeuristicExtractor.extract_locations(SAMPLE_DOC)
    print(f"\nExtracted {len(locations)} locations: {locations}")

    # Extract relationships
    relationships = HeuristicExtractor.extract_relationships(SAMPLE_DOC)
    print(f"\nExtracted {len(relationships)} relationships:")
    for rel in relationships:
        print(f"  - {rel['subject']} --[{rel['relationship_type']}]--> {rel['object']}")


def example_full_synthesis():
    """Example 3: Full synthesis into wiki."""
    print("\n" + "=" * 60)
    print("Example 3: Full Wiki Synthesis")
    print("=" * 60)

    wiki_dir = Path("./wiki_example_output")
    builder = WikiBuilder(wiki_dir=wiki_dir)

    result = builder.synthesize_document(
        doc_id="example_tesla_expansion_2024",
        doc_title="Tesla Announces $5B Georgia Expansion",
        url="https://example.com/tesla-expansion-2024",
        content=SAMPLE_DOC,
        company_name="Tesla",
    )

    print(f"\nSynthesis result:")
    print(f"  Status: {result.get('status', 'processing')}")
    print(f"  Entities extracted: {len(result.get('extracted_entities', []))}")
    print(f"  Pages updated: {len(result.get('updated_pages', []))}")

    for entity in result.get("extracted_entities", []):
        print(f"\n  Entity: {entity.get('entity_name')}")
        print(f"    Type: {entity.get('entity_type')}")
        print(f"    Pages: {entity.get('pages_updated')}")

    # Show created wiki pages
    print(f"\nGenerated wiki files:")
    for md_file in sorted(wiki_dir.glob("**/*.md")):
        print(f"  - {md_file.relative_to(wiki_dir)}")
        # Show first few lines
        content = md_file.read_text(encoding="utf-8")
        lines = content.split("\n")[:5]
        for line in lines:
            if line.strip():
                print(f"    {line}")

    # Cleanup
    import shutil
    shutil.rmtree(wiki_dir, ignore_errors=True)
    print(f"\n[Cleaned up example output]")


def example_batch_synthesis():
    """Example 4: Batch synthesis from multiple documents."""
    print("\n" + "=" * 60)
    print("Example 4: Batch Synthesis")
    print("=" * 60)

    from src.wiki_integration import synthesize_downloaded_batch

    # Simulate multiple downloaded documents
    documents = [
        {
            "doc_id": "doc_001",
            "doc_title": "Tesla Georgia Expansion 2024",
            "url": "https://example.com/tesla-expansion",
            "content": SAMPLE_DOC,
            "company_name": "Tesla",
        },
        {
            "doc_id": "doc_002",
            "doc_title": "Panasonic Georgia Operations",
            "url": "https://example.com/panasonic-ga",
            "content": "Panasonic operates a battery manufacturing facility in Georgia...",
            "company_name": "Panasonic",
        },
    ]

    wiki_dir = Path("./wiki_batch_example")
    results = synthesize_downloaded_batch(
        documents,
        wiki_dir=wiki_dir,
        llm_model="mistral",
    )

    print(f"\nBatch synthesis results:")
    print(f"  Total documents: {results.get('total_documents')}")
    print(f"  Processed: {results.get('processed')}")
    print(f"  Entities extracted: {results.get('total_entities')}")
    print(f"  Pages updated: {results.get('pages_updated')}")

    # Cleanup
    import shutil
    shutil.rmtree(wiki_dir, ignore_errors=True)
    print(f"\n[Cleaned up example output]")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("LLM Wiki Builder Examples")
    print("=" * 60)

    # Run heuristic example (no LLM required)
    example_heuristic_extraction()

    # Run basic extraction (requires Ollama running)
    try:
        import ollama
        example_basic_extraction()
        example_full_synthesis()
        example_batch_synthesis()
    except ImportError:
        print(
            "\n⚠️  Ollama not available. Install with: pip install ollama"
        )
        print("   Or install Ollama from https://ollama.ai")
    except Exception as exc:
        print(f"\n⚠️  Could not run LLM examples: {exc}")
        print("   Make sure Ollama is running: ollama serve")

    print("\n" + "=" * 60)
    print("Examples complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
