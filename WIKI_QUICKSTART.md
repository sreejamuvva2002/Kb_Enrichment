# Wiki Quickstart - Get Running in 5 Minutes

## Prerequisites Checklist

- [ ] Python 3.9+ installed
- [ ] Ollama installed (https://ollama.ai)
- [ ] 6GB+ available RAM
- [ ] `pip install ollama` (Python package)

## Step 1: Install & Start Ollama (2 min)

```bash
# macOS / Linux
curl -fsSL https://ollama.ai/install.sh | sh

# Windows: Download from https://ollama.ai/download

# Pull Mistral model
ollama pull mistral

# Start Ollama server (keep this running)
ollama serve
```

You'll see: `Listening on 127.0.0.1:11434`

## Step 2: Install Python Dependencies (1 min)

```bash
cd Kb_Enrichment
pip install ollama
# (You may already have this from other requirements)
```

## Step 3: Test Local LLM Works (1 min)

```bash
python -c "
import ollama
response = ollama.generate(model='mistral', prompt='What is 2+2?', stream=False)
print(response['response'])
"
```

Should print something like: `2+2 equals 4`

## Step 4: Run Wiki Examples (1 min)

```bash
python examples/wiki_example.py
```

You'll see:
```
============================================================
LLM Wiki Builder Examples
============================================================

Example 1: Basic LLM Extraction
...
Extracted 3 facts
  - facility: Tesla Georgia Plant
  - investment: Georgia Expansion 2024
  - company: Panasonic
```

## Step 5: Enable in Your Pipeline

Edit `config/settings.yaml`:
```yaml
wiki_enabled: true
wiki_llm_model: "mistral"
wiki_llm_base_url: "http://localhost:11434"
wiki_dry_run: false
```

## Step 6: Run Pipeline with Wiki

```bash
# Run your normal pipeline
python main.py --mode single-company --company "Tesla"

# After downloads, wiki automatically synthesizes
```

Check generated wiki:
```bash
ls -la wiki/companies/
cat wiki/companies/tesla.md
```

## That's it! 🎉

### What Just Happened

1. **Downloaded documents** → fed to local LLM
2. **LLM extracted entities** → companies, facilities, investments
3. **Wiki pages created** → one per entity with links to sources
4. **Future queries** → update existing wiki pages (knowledge compounds)

### Next: Explore

- **View generated wiki:** `open wiki/companies/` (or `explorer wiki\companies\` on Windows)
- **Check synthesis results:** Look at `results.log` or pipeline output
- **Customize extraction:** Edit `config/wiki_schema.json`
- **Tweak LLM model:** Use `ollama pull llama2` for alternatives

### Troubleshooting

**"Connection refused" error:**
```bash
# Ollama not running, start it:
ollama serve
```

**"No such file or directory: ollama":**
```bash
# Ollama not installed:
pip install ollama
```

**"Out of memory":**
```bash
# Reduce chunk size in config/wiki_schema.json:
"chunk_size": 500,  # was 800
"chunk_overlap": 50,  # was 100
```

**LLM extraction taking too long:**
- Normal (Mistral): 3-8 seconds per chunk
- 100 documents = 30-120 minutes
- Consider running overnight or in background

### Files Created

```
src/
├── wiki_builder.py          # Core synthesis engine
├── wiki_integration.py      # Pipeline hooks  
└── wiki_extractors.py       # Fallback heuristics

config/
└── wiki_schema.json         # Entity definitions

wiki/                        # Generated knowledge base
├── companies/
├── facilities/
├── investments/
└── relationships/

examples/
└── wiki_example.py          # Runnable examples

WIKI_*.md                    # Documentation
```

### Next Steps

1. **Let it run:** Synthesize your existing downloaded documents
   ```bash
   python main.py --mode wiki-rebuild
   ```

2. **Explore results:** Browse generated wiki pages
   ```bash
   find wiki -name "*.md" | head -20
   ```

3. **Monitor growth:**
   ```bash
   python -c "from src.wiki_integration import get_wiki_summary; \
   summary = get_wiki_summary(); \
   print(f\"Wiki has {summary['entity_counts']}\")"
   ```

4. **Customize:** Edit extraction rules in `config/wiki_schema.json`

### Performance Tips

- **First run:** Slower (extracting from all docs)
- **Subsequent runs:** Only new documents (incremental)
- **Batch mode:** Process 10-20 docs at a time for stability
- **Overnight:** Schedule large synthesis runs off-hours

### FAQ

**Q: Can I use a different model?**  
A: `ollama pull llama2` then update `config/settings.yaml` `wiki_llm_model: llama2`

**Q: How long does extraction take?**  
A: ~5-10 seconds per 1000-word document. 100 docs = 1-2 hours.

**Q: What if extraction fails?**  
A: Fallback heuristics kick in (regex patterns). Low-confidence facts marked for review.

**Q: Can I rebuild the wiki?**  
A: Yes: `python main.py --mode wiki-rebuild`

**Q: Does wiki slow down the pipeline?**  
A: No - runs after downloads complete. Can disable with `wiki_enabled: false`

---

**Happy wiki building!** 📚

Questions? See:
- `WIKI_ARCHITECTURE.md` - Deep dive design
- `WIKI_INTEGRATION.md` - Full integration guide  
- `examples/wiki_example.py` - Runnable code examples
