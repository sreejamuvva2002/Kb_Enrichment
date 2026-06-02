# LLM Wiki Architecture - Design Document

## Overview

The **LLM Wiki system** transforms your DDG search → download → track pipeline into a **knowledge accumulation system** that builds persistent markdown pages linking facts to sources.

Instead of:
```
Query → Search → Download → Store → (knowledge lost, re-derive on next query)
```

You get:
```
Query → Search → Download → Extract → Update Wiki → (knowledge persists and compounds)
```

## Three Layers (Karpathy's LLM Wiki Pattern)

### 1. **Raw Sources** (Immutable)
Your downloaded documents in storage:
- `s3://bucket/doc_xyz/content.html`
- Referenced but never modified
- Each document has: doc_id, URL, company, source_backend, download_status

### 2. **The Wiki** (LLM-maintained, persistent)
Markdown files organized by entity type:
```
wiki/
├── companies/
│   └── tesla.md          # Company profile with locations, relationships
├── facilities/
│   └── georgia_plant.md  # Facility details with capacity, permits
├── investments/
│   └── 2024_expansion.md # Investment announcements with amounts, jobs
└── relationships/
    └── tesla_suppliers.md # Supply chain connections
```

Each page:
- Contains synthesized facts from multiple documents
- Links back to source documents (evidence trail)
- Gets updated incrementally as new documents arrive
- Never loses information (only adds/refines)

### 3. **Schema** (Configuration)
Defines extraction rules and page structures:
- `config/wiki_schema.json` - Entity types, properties, relationships
- Example: `company` has properties `[name, location, subsidiaries, ...]`
- Rules: `investment` must extract `[amount, date, location, jobs]`

## Data Flow

```
Downloaded Documents
        │
        ├─ Load content from storage
        │
        ├─ [TextChunker]
        │   Break into 500-1000 token chunks
        │   (avoids context window limits of local LLMs)
        │
        ├─ [LocalLLMClient] (Ollama/Mistral)
        │   Per-chunk fact extraction
        │   Structured JSON output
        │   Temperature=0.3 (deterministic)
        │
        ├─ [HeuristicExtractor] (Fallback)
        │   Regex patterns for: amounts, dates, locations
        │   Used when LLM extraction fails or low confidence
        │
        ├─ [WikiBuilder]
        │   Deduplicate facts across chunks
        │   Route entities to correct wiki pages
        │   Link documents as evidence
        │
        └─ [WikiPage] 
            Markdown files (incremental updates)
            Version: Each update preserves history
```

## Key Design Decisions for Local LLMs

### 1. **Chunking**
- Split documents into 500-1000 token pieces (~2000 chars)
- 100-token overlap to maintain context
- Avoids overwhelming small context windows (local models: 2K-8K)

### 2. **Structured Output**
- LLM returns JSON (not prose)
- Format: `{"entity_type": "company", "entity_name": "...", "facts": [...]}`
- Easier for local models to format correctly
- Easy to parse and merge with existing wiki

### 3. **Temperature=0.3**
- Low temperature makes output deterministic
- Reduces variance in extraction (important for local models)
- Still allows some flexibility (0.0 = too rigid for creativity)

### 4. **Fallback Heuristics**
When LLM extraction fails or low confidence:
- Regex for amounts: `\$\d+\s*(million|billion|M|B)`
- Regex for dates: `20\d{2}|Q[1-4]\s+20\d{2}`
- Regex for locations: `(city|county),?\s*Georgia`
- Keyword matching for relationships: `supplier`, `partner`, `owns`

**Result:** Reliable extraction even with imperfect LLM

### 5. **Incremental Updates**
- New facts update existing pages (don't replace)
- Same entity extracted multiple times = merged, not duplicated
- Document links accumulated (evidence trail grows)
- Can rebuild wiki by re-extracting all documents

## File Structure

```
Kb_Enrichment/
├── src/
│   ├── wiki_builder.py         # Main synthesis engine
│   │   ├── LocalLLMClient      # Interface to Ollama
│   │   ├── TextChunker         # Document splitting
│   │   ├── WikiPage            # Markdown page management
│   │   └── WikiBuilder         # Orchestrator
│   │
│   ├── wiki_integration.py     # Pipeline hooks
│   │   ├── prepare_documents_for_wiki()
│   │   ├── synthesize_downloaded_batch()
│   │   └── get_wiki_summary()
│   │
│   └── wiki_extractors.py      # Heuristic fallbacks
│       ├── HeuristicExtractor
│       └── fill_facts_with_heuristics()
│
├── config/
│   └── wiki_schema.json        # Entity types, extraction rules
│
├── wiki/                       # Generated knowledge base
│   ├── companies/
│   ├── facilities/
│   ├── investments/
│   └── relationships/
│
├── WIKI_INTEGRATION.md         # Integration guide
├── WIKI_ARCHITECTURE.md        # This file
└── examples/
    └── wiki_example.py         # Standalone usage examples
```

## Integration Points in Your Pipeline

### Point 1: After `download_entries()` (Recommended)
```python
# In main.py, after each batch of downloads
download_stats = download_entries(entries, downloader, tracker, run_id, settings)

# NEW: Synthesize to wiki
if settings.get("wiki_enabled"):
    wiki_results = synthesize_downloaded_batch(
        entries,
        llm_model="mistral"
    )
```

### Point 2: New pipeline mode
```bash
python main.py --mode wiki-only
# Re-extract all downloaded documents
```

### Point 3: Periodic wiki rebuilds
```bash
python main.py --mode wiki-rebuild
# Rebuild entire wiki from scratch (for schema updates)
```

## Example: What Gets Extracted

**Input document:**
> "Tesla announced a $5 billion expansion of its Georgia manufacturing facility. The investment will create 2,500 jobs in Cobb County..."

**Extracted facts:**
```json
{
  "entity_type": "investment",
  "entity_name": "Tesla Georgia Expansion 2024",
  "amount": "$5 billion",
  "jobs": 2500,
  "location": "Cobb County, Georgia",
  "company": "Tesla",
  "date": "2024",
  "source_doc": "doc_12345"
}
```

**Generated wiki pages:**
1. `wiki/companies/tesla.md` - Add "Investments" section
2. `wiki/investments/tesla_georgia_expansion_2024.md` - New page
3. `wiki/facilities/tesla_georgia_plant.md` - Update "Investment History"
4. `wiki/relationships/tesla_supply_chain.md` - If suppliers mentioned

**Result:** Each page links back to source documents as evidence

## Local LLM Model Selection

| Model | Speed | Quality | Memory | Recommended |
|-------|-------|---------|--------|-------------|
| **Mistral 7B** | ⚡⚡⚡ | ✓✓ | 5GB | YES - default |
| Llama 2 7B | ⚡⚡ | ✓✓ | 4GB | Alternative |
| Neural Chat 7B | ⚡⚡ | ✓✓ | 4GB | Good for instructions |
| Llama 2 13B | ⚡ | ✓✓✓ | 8GB | Higher quality (slower) |

**Setup:**
```bash
ollama pull mistral
ollama serve  # Starts on localhost:11434
```

## Fallback Logic

When LLM extraction doesn't work:
1. Try LLM extraction on chunk
2. If LLM returns invalid JSON or empty → fallback heuristics
3. Heuristics extract: amounts, dates, locations, relationships
4. Merge heuristic results with any partial LLM output
5. Mark low-confidence facts for human review

```python
llm_facts = builder.llm.extract_facts(chunk, prompt)
if not llm_facts or "entity_type" not in llm_facts:
    llm_facts = {}  # Empty fallback

# Fill gaps with heuristics
enhanced = fill_facts_with_heuristics(
    llm_facts,
    text=chunk,
    fallback=True
)
```

## Wiki Page Format

**Example: `wiki/companies/tesla.md`**

```markdown
# Tesla

Last updated: 2024-06-01T15:32:00Z

## Overview
American electric vehicle manufacturer with operations in Georgia.

## Key Facts
- Headquarters: California
- Georgia facility operational since 2022
- Primary products: Electric vehicles, batteries

## Location
Atlanta metropolitan area, Cobb County, Georgia

## Facilities
- [Tesla Georgia Plant](../facilities/tesla_georgia_plant.md)

## Investments
- 2024: $5 billion Georgia expansion
- 2,500 jobs created

## Relationships
- **Supplier**: Panasonic
- **Customer**: Major OEMs
- **Partner**: Georgia economic development

## News
- 2024-05-15: Announced Georgia expansion
- 2023-10-01: Facility ramp announced

## Sources
- [Tesla Announces $5B Georgia Expansion](https://example.com) (doc_id: doc_001)
- [SEC Filing](https://sec.gov) (doc_id: doc_002)
- [Georgia Power Partnership](https://gapower.com) (doc_id: doc_003)
```

## Performance Characteristics

### Extraction Speed (per document)
- **Document size**: ~10KB typical
- **Chunks**: ~10-15 chunks per doc
- **Time per chunk**: 3-8 seconds (Mistral on typical hardware)
- **Total per doc**: 30-120 seconds
- **Batch of 100**: ~1-2 hours

### Storage
- **Raw markdown wiki**: ~10MB per 1000 entities
- **No image/binary storage** (just text links)
- **Incremental updates** (pages grow, never shrink)

### Memory Usage
- **Ollama + Mistral**: ~6GB
- **WikiBuilder process**: ~500MB-1GB
- **Total**: ~7GB recommended

## Updating the Wiki Schema

Edit `config/wiki_schema.json`:

```json
{
  "entity_types": [
    {
      "type": "your_new_entity",
      "properties": ["prop1", "prop2"],
      "extraction_priority": "high"
    }
  ]
}
```

Update `wiki_builder.py` to add handler:
```python
elif entity_type == "your_new_entity":
    page_path = self.wiki_dir / "your_entities" / f"{slug}.md"
    self._update_your_entity_page(page_path, ...)
```

## Limitations & Workarounds

| Issue | Impact | Workaround |
|-------|--------|-----------|
| Local LLM hallucination | Facts may be inaccurate | Heuristic fallbacks; mark for review |
| Small context window | Can't process full doc at once | Chunk into pieces (already done) |
| Slow inference | Processing takes time | Run overnight; batch jobs |
| PDF extraction needed | Many documents are PDFs | Add `pdfplumber` library |
| Relationship extraction hard | Connection extraction unreliable | Heuristics + manual linking |

## Next Steps

1. **Setup Ollama:**
   ```bash
   ollama pull mistral
   ollama serve
   ```

2. **Try example:**
   ```bash
   python examples/wiki_example.py
   ```

3. **Update settings:**
   ```yaml
   # config/settings.yaml
   wiki_enabled: true
   wiki_llm_model: mistral
   ```

4. **Integrate into pipeline:**
   - Edit `main.py` after `download_entries()`
   - Call `synthesize_downloaded_batch()`

5. **Monitor wiki growth:**
   ```bash
   python -c "from src.wiki_integration import get_wiki_summary; print(get_wiki_summary())"
   ```

## References

- **Original concept**: [LLM Wiki by Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- **Ollama**: https://ollama.ai
- **Mistral model**: https://mistral.ai
- **Markdown format**: Use CommonMark (compatible with GitHub)
