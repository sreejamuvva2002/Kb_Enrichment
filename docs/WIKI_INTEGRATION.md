# LLM Wiki Integration Guide

Integrating the wiki synthesis system into your existing pipeline.

## Overview

The wiki system is a **post-processing layer** that runs after documents are downloaded. It:

1. **Extracts entities** from downloaded documents using a local LLM (Mistral, Llama2, etc. via Ollama)
2. **Builds/updates markdown pages** for companies, facilities, investments, and relationships
3. **Links documents** as evidence sources
4. **Uses heuristic fallbacks** when LLM extraction is uncertain

## Prerequisites

### 1. Install Ollama (or similar local LLM server)

```bash
# macOS / Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows - download from https://ollama.ai

# Start Ollama
ollama serve
```

### 2. Pull a model

```bash
# Mistral 7B (recommended - fast, good quality)
ollama pull mistral

# Or Llama 2 (larger, slower)
ollama pull llama2

# Or Neural Chat (optimized for instructions)
ollama pull neural-chat
```

Verify it's running:
```bash
curl http://localhost:11434/api/tags
```

### 3. Update settings

Update `config/settings.yaml`:
```yaml
wiki_enabled: true
wiki_llm_model: "mistral"  # or llama2, neural-chat
wiki_llm_base_url: "http://localhost:11434"
wiki_dry_run: false  # Set to true for testing
```

## Integration into Main Pipeline

### Option A: Add to existing download flow (minimal change)

In `main.py`, after `download_entries()`:

```python
from src.wiki_integration import synthesize_downloaded_batch

# After successful downloads
if args.mode in {"full", "pilot", "resume", "single-company"}:
    download_stats = download_entries(discovered_entries, downloader, tracker, run_id, settings)
    for key in download_stats:
        stats[key] += download_stats[key]
    
    # NEW: Synthesize into wiki
    if settings.get("wiki_enabled"):
        wiki_results = synthesize_downloaded_batch(
            discovered_entries,
            llm_model=settings.get("wiki_llm_model", "mistral"),
            dry_run=settings.get("wiki_dry_run", False),
        )
        LOGGER.info("Wiki synthesis: %s", wiki_results)
```

### Option B: Create new wiki-only mode

Add to `parse_args()`:
```python
parser.add_argument(
    "--mode",
    choices=[
        # ... existing modes ...
        "wiki-only",
        "wiki-rebuild",
    ],
)
```

Add to main:
```python
if args.mode == "wiki-only":
    run_wiki_synthesis_only(args)
    return

if args.mode == "wiki-rebuild":
    run_wiki_rebuild_from_storage(args)
    return
```

## Running the Wiki

### Test extraction on a single document

```bash
python -c "
from src.wiki_builder import WikiBuilder
from pathlib import Path

builder = WikiBuilder()
result = builder.synthesize_document(
    doc_id='test_001',
    doc_title='Test Document',
    url='http://example.com',
    content=open('sample.txt').read(),
    company_name='Tesla',
)
print(result)
"
```

### Synthesize batch of documents

```bash
python -c "
from src.wiki_integration import synthesize_downloaded_batch

docs = [
    {
        'doc_id': 'doc_1',
        'doc_title': 'Investment Announcement',
        'url': 'http://example.com/news',
        'content': open('file1.txt').read(),
        'company_name': 'Tesla',
    },
    # ... more docs
]

results = synthesize_downloaded_batch(docs, llm_model='mistral')
print(f\"Processed: {results['processed']}, Entities: {results['total_entities']}\")
"
```

### Run in pipeline mode

```bash
python main.py --mode single-company --company "Tesla"
# (automatically synthesizes docs to wiki after download)
```

## Wiki Structure

```
wiki/
├── companies/
│   ├── tesla.md
│   ├── panasonic.md
│   └── ...
├── facilities/
│   ├── tesla_georgia_plant.md
│   └── ...
├── investments/
│   ├── georgia_ev_tax_credits_2024.md
│   └── ...
└── relationships/
    └── tesla_supplier_relationships.md
```

## Example Wiki Page

**`wiki/companies/tesla.md`**
```markdown
# Tesla

## Key Facts
- American electric vehicle manufacturer
- Primary operations in Georgia

## Location
Atlanta, Georgia metro area

## Facilities
- See [Tesla Georgia Plant](../facilities/tesla_georgia_plant.md)

## Investments
- $5 billion announced 2024

## Products/Services
- Electric vehicles
- Battery systems
- Solar products

## Sources
- [SEC Filing](http://sec.gov) (doc_id: doc_xyz)
- [Georgia Power News](http://georgiapower.com) (doc_id: doc_abc)
```

## Local LLM Model Comparison

| Model | Speed | Quality | Memory | Best For |
|-------|-------|---------|--------|----------|
| Mistral 7B | Fast | Good | 5GB | **Default choice** |
| Llama 2 7B | Medium | Good | 4GB | Alternative |
| Neural Chat 7B | Medium | Good | 4GB | Instruction-following |
| Llama 2 13B | Slow | Better | 8GB | Higher quality |

**Recommendation:** Start with `mistral` (good speed/quality balance)

## Troubleshooting

### LLM not responding

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
killall ollama
ollama serve
```

### Low extraction quality

- Use larger model: `llama2:13b`
- Reduce `chunk_size` in `wiki_schema.json` (smaller context)
- Lower `temperature` for more deterministic output
- Check extracted facts in `wiki/` directories

### Out of memory

- Use smaller model: `mistral` or `neural-chat`
- Reduce batch size in settings
- Increase `chunk_overlap` to process longer documents in smaller chunks

## Advanced: Custom Extraction Prompts

Edit `wiki_builder.py` `_extract_chunk_facts()` to customize LLM prompts:

```python
prompt = f"""Extract key facts from this text as JSON.

IMPORTANT: You are building a knowledge base about Georgia EV supply chain.

Focus on:
- Companies and facilities
- Investments and jobs announcements
- Supply chain relationships
- Regulatory information

TEXT:
{chunk[:1500]}

Return JSON array with extracted entities:
"""
```

## Monitoring

Check wiki synthesis results:

```bash
python -c "
from src.wiki_integration import get_wiki_summary
summary = get_wiki_summary()
print(f\"Wiki contains: {summary['entity_counts']}\")
"
```

View generated pages:

```bash
ls -la wiki/companies/
cat wiki/companies/tesla.md
```

## FAQ

**Q: Can I use a different model?**  
A: Yes - any model running on Ollama. Update `wiki_schema.json` `llm_settings.model`

**Q: Does wiki synthesis slow down the pipeline?**  
A: Minimal impact - runs after downloads complete. Can disable with `wiki_enabled: false`

**Q: How do I rebuild the wiki from existing documents?**  
A: Use `--mode wiki-rebuild` to re-extract from all downloaded docs

**Q: Can I combine LLM extraction with heuristics?**  
A: Yes - set `fallback_strategies.extraction_failure: use_heuristic_regex` in schema

**Q: How do I handle PDFs?**  
A: Add PDF extraction library (pdfplumber, PyPDF2) and load text in `wiki_integration.py` `content_loader()`
