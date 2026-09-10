# Jina AI Models

## Models

| Model | Type | Multilingual | Hugging Face |
|-------|------|-------------|-------------|
| jina-reranker-v1-turbo-en | Reranker | No (English) | [jinaai/jina-reranker-v1-turbo-en](https://huggingface.co/jinaai/jina-reranker-v1-turbo-en) |
| jina-reranker-v2-base-multilingual | Reranker | Yes (100+ languages) | [jinaai/jina-reranker-v2-base-multilingual](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual) |
| jina-embeddings-v2-base-code | Embedding | Code + English | [jinaai/jina-embeddings-v2-base-code](https://huggingface.co/jinaai/jina-embeddings-v2-base-code) |
| jina-embeddings-v2-base-en | Embedding | English | [jinaai/jina-embeddings-v2-base-en](https://huggingface.co/jinaai/jina-embeddings-v2-base-en) |

## Original-model and cache-repository license

The original models and the exact Jina cache repositories selected by FastEmbed declare Apache
License 2.0. Both provenance layers are recorded explicitly in `models-manifest.toml`.

## Authors

Jina AI — [jina.ai](https://jina.ai/)

## Citation

```bibtex
@misc{günther2023jina,
    title={Jina Embeddings 2: 8192-Token General-Purpose Text Embeddings for Long Documents},
    author={Michael Günther and Jackmin Ong and Isabelle Mohr and Alaeddine Abdessalem and Tanguy Abel and Mohammad Kalim Akram and Susana Guzman and Georgios Mastrapas and Saba Sturua and Bo Wang and Maximilian Werk and Nan Wang and Han Xiao},
    year={2023},
    eprint={2310.19923},
    archivePrefix={arXiv},
    primaryClass={cs.CL}
}
```

## Original Source

All cache repositories are published at [huggingface.co/jinaai](https://huggingface.co/jinaai).
The exact ONNX paths consumed by FastEmbed 6.0.2 are recorded in `models-manifest.toml`.
