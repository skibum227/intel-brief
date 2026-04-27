# Future Work

## 1. Local LLM Chat Q&A with RAG

### Overview
Add a `--chat` mode that lets you ask questions against your full brief history and raw connector data using a local LLM. Uses RAG (Retrieval-Augmented Generation) so the model only needs a small context window — feasible on a 16GB M1 Pro.

### Architecture

```
User question
    │
    ▼
Embed question (nomic-embed-text, local, ~300MB)
    │
    ▼
Vector search against indexed briefs (ChromaDB/LanceDB, file-based)
    │
    ▼
Top 5-10 relevant chunks (~2-3K tokens)
    │
    ▼
Local LLM (llama.cpp, 8B Q4_K_M model, ~5GB RAM)
    │
    ▼
Answer with citations (brief date + section)
```

### Components

**1. Embedding model**
- `nomic-embed-text` via llama.cpp or sentence-transformers
- ~300MB, runs on CPU, produces 768-dim vectors
- Alternative: `mxbai-embed-large` (1024-dim, slightly better quality)

**2. Vector store**
- ChromaDB (pip install chromadb) or LanceDB (pip install lancedb)
- Both are file-based, no server — store at `~/.config/intel-brief/vectordb/`
- Grows ~1-2MB per month of daily briefs

**3. Local LLM**
- llama.cpp with Metal acceleration (M1 Pro GPU)
- Recommended models (Q4_K_M quantization):
  - `Llama-3.1-8B-Instruct` — 5GB, good general quality
  - `Qwen2.5-7B-Instruct` — 5GB, strong at structured data
  - `Mistral-7B-Instruct-v0.3` — 5GB, fast
- Context window: 8K tokens is plenty (RAG handles retrieval)
- Expected response time: 2-5 seconds on M1 Pro

**4. Indexing pipeline** (new module: `src/indexer.py`)
- Triggered after each brief write in `run.py`
- Chunks each brief by `##` section headers
- Each chunk stored with metadata: `{date, section, source_file}`
- Also indexes raw connector data if desired (optional, adds volume)
- Incremental — only indexes new/changed files

**5. Chat interface** (new mode in `run.py`)
```bash
python run.py --chat "what's the status of the loan pilot?"
python run.py --chat  # interactive REPL mode
```

### Chunking Strategy

Briefs are already well-structured markdown. Chunk by section:
```
Chunk 1: "2026-04-25 | Project Pulse | Loan pilot delayed pending..."
Chunk 2: "2026-04-25 | Priorities & Action Items | 🔴 Review risk model..."
Chunk 3: "2026-04-25 | Who Needs a Response | Alice — Slack, loan pilot..."
Chunk 4: "2026-04-25 | My Notes | Spoke with compliance about..."
```

Each chunk is ~100-500 tokens. Prefix with date and section name for context.

### Query Flow

1. Embed user question → query vector
2. Cosine similarity search → top 5-10 chunks
3. Build prompt:
   ```
   You are answering questions about JD's intel briefs. Use only the
   provided context. Cite the date and section for each fact.

   Context:
   [Apr 25, Project Pulse] Loan pilot delayed pending compliance...
   [Apr 23, Priorities] 🔴 Review loan pilot risk model with Alice...

   Question: What's the status of the loan pilot?
   ```
4. LLM generates answer from retrieved context

### Hardware Requirements (16GB M1 Pro)

| Component | RAM | Notes |
|-----------|-----|-------|
| Embedding model | ~300MB | Loaded on demand, can unload after indexing |
| Vector DB | ~50MB | File-based, memory-mapped |
| 8B LLM (Q4_K_M) | ~5GB | Persistent during chat session |
| KV cache (8K ctx) | ~500MB | Scales with context size |
| **Total** | **~6GB** | Leaves ~10GB for OS + apps |

### Dependencies to Add

```
# requirements-local.txt (separate from main requirements.txt)
chromadb>=0.4.0        # or lancedb>=0.4.0
sentence-transformers>=2.2.0  # for embedding (or use llama.cpp embeddings)
```

llama.cpp installed separately:
```bash
brew install llama.cpp
# Download a model GGUF:
# huggingface-cli download TheBloke/Llama-3.1-8B-Instruct-GGUF llama-3.1-8b-instruct.Q4_K_M.gguf
```

### Config Addition

```yaml
local_llm:
  enabled: false
  provider: llama_cpp          # or "ollama"
  model_path: ~/.local/share/llama/llama-3.1-8b-instruct.Q4_K_M.gguf
  base_url: http://localhost:8080/v1   # llama-server endpoint
  embedding_model: nomic-embed-text
  vectordb_path: ~/.config/intel-brief/vectordb
  retrieval_top_k: 8
```

### Implementation Order

1. **Indexer** (`src/indexer.py`) — chunk briefs, embed, store in vector DB
2. **Retriever** (`src/retriever.py`) — query vector DB, return ranked chunks
3. **Chat** (`src/chat.py`) — build prompt from chunks, call local LLM, display answer
4. **Wire into run.py** — `--chat` flag, auto-index after brief generation

### Optional: Style Fine-tuning

Not for data (RAG handles that) but for response style. If the vanilla model's answers aren't formatted or toned the way you want:

1. Collect 50-100 Q&A pairs you like (questions you'd ask + ideal answers)
2. QLoRA fine-tune the 8B model (fits in 16GB, ~2-3 hours one-time)
3. Use the LoRA adapter with the base model going forward

This is one-time, not recurring — the RAG pipeline handles all data freshness.

---

## 2. Obsidian Knowledge Graph Links

### Overview
Post-process briefs to embed `[[wikilinks]]` for people, projects, and tickets. Creates a connected knowledge graph across all briefs in Obsidian.

### What Gets Linked
- `**Alice Smith**` → `**[[Alice Smith]]**`
- `DE-123` → `[[DE-123]]`
- `#data-engineering` channel refs → `[[#data-engineering]]`
- Frontmatter tags: `tags: [daily-brief, blocked, urgent]`

### Name Normalization
Build a canonical name map from Slack user cache (`~/.config/intel-brief/slack_channel_cache.json` already stores user ID→name mappings). Ensure "Alice", "Alice S.", "Alice Smith" all link to `[[Alice Smith]]`.

### Implementation
- New function in `obsidian.py`: `_add_wikilinks(text: str, name_map: dict) -> str`
- Called in `write_brief()` before writing to disk
- Regex-based: scan for bold names, Jira keys, channel references
- ~2-3 hours of work
