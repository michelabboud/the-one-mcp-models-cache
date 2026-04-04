# the-one-mcp-models-cache

Pre-packaged ONNX embedding and reranker models for [the-one-mcp](https://github.com/michelabboud/the-one-mcp).

Model files are distributed via **GitHub Releases** (not stored in git). Each release contains the ONNX model files for one or more model families.

## Why This Exists

`the-one-mcp` uses [fastembed-rs](https://github.com/Anush008/fastembed-rs) for local embedding. By default, fastembed downloads models from Hugging Face on first use. This cache provides:

- **Faster installs** — download from GitHub CDN instead of Hugging Face
- **Offline support** — pre-download models before going offline
- **Deterministic builds** — pin exact model versions
- **Mirror resilience** — works even if Hugging Face is down

## Model Families

| Family | Provider | Models | License |
|--------|----------|--------|---------|
| [sentence-transformers](sentence-transformers/) | Sentence-Transformers | all-MiniLM-L6-v2, all-MiniLM-L12-v2 | Apache 2.0 |
| [baai](baai/) | BAAI (Beijing Academy of AI) | BGE-base/large/small-en-v1.5, BGE-reranker-base, BGE-reranker-v2-m3 | MIT |
| [intfloat](intfloat/) | intfloat | multilingual-e5-large/base/small | MIT |
| [nomic-ai](nomic-ai/) | Nomic AI | nomic-embed-text-v1, nomic-embed-text-v1.5 | Apache 2.0 |
| [mixedbread-ai](mixedbread-ai/) | Mixedbread AI | mxbai-embed-large-v1 | Apache 2.0 |
| [alibaba-gte](alibaba-gte/) | Alibaba DAMO Academy | gte-base-en-v1.5, gte-large-en-v1.5 | MIT |
| [jina-ai](jina-ai/) | Jina AI | jina-reranker-v1-turbo-en, jina-reranker-v2-base-multilingual | Apache 2.0 |

## Download

### Quick Download (single model)

```bash
# Download a specific model from the latest release
gh release download latest -R michelabboud/the-one-mcp-models-cache -p "BGE-large-en-v1.5.tar.gz"
```

### Using the download script

```bash
# Download the default model (BGE-large-en-v1.5)
bash scripts/download-model.sh

# Download a specific model
bash scripts/download-model.sh all-MiniLM-L6-v2

# Download all models
bash scripts/download-model.sh --all

# List available models
bash scripts/download-model.sh --list
```

### Manual Download

Go to [Releases](https://github.com/michelabboud/the-one-mcp-models-cache/releases) and download the `.tar.gz` archive for your model. Extract to `~/.fastembed_cache/`.

## Release Format

Each release is tagged with the fastembed crate version it targets (e.g., `fastembed-v4`). Release assets are `.tar.gz` archives, one per model:

```
BGE-large-en-v1.5.tar.gz          # 130MB — default model
all-MiniLM-L6-v2.tar.gz           # 23MB
multilingual-e5-large.tar.gz      # 220MB
...
```

Each archive extracts to the fastembed cache directory structure:

```
~/.fastembed_cache/
└── fast-bge-large-en-v1.5/        # fastembed's internal naming
    ├── model.onnx
    ├── tokenizer.json
    ├── config.json
    └── ...
```

## License & Attribution

**This repository does not contain any model weights in git.** Model weights are distributed via GitHub Releases.

All models are redistributed under their original licenses. Each family directory contains:
- `LICENSE` — the original model license
- `ATTRIBUTION.md` — credits, Hugging Face links, citation info

We do not claim ownership of any model. All credit belongs to the original authors.

## Related

- [the-one-mcp](https://github.com/michelabboud/the-one-mcp) — the MCP broker that uses these models
- [fastembed-rs](https://github.com/Anush008/fastembed-rs) — the Rust embedding library
- [Hugging Face](https://huggingface.co/) — original model host
