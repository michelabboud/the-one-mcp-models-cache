# Nomic AI Models

## Models

| Model | Dims | Size | Context | Hugging Face |
|-------|------|------|---------|-------------|
| nomic-embed-text-v1 | 768 | ~55MB | 8192 tokens | [nomic-ai/nomic-embed-text-v1](https://huggingface.co/nomic-ai/nomic-embed-text-v1) |
| nomic-embed-text-v1.5 | 768 | ~55MB | 8192 tokens | [nomic-ai/nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) |
| nomic-embed-vision-v1.5 | 768 | See manifest | Image | [nomic-ai/nomic-embed-vision-v1.5](https://huggingface.co/nomic-ai/nomic-embed-vision-v1.5) |

## Original-model and cache-repository license

The original models and the exact Nomic cache repositories selected by FastEmbed declare Apache
License 2.0. Both provenance layers are recorded explicitly in `models-manifest.toml`.

## Authors

Nomic AI — [nomic.ai](https://www.nomic.ai/)

## Citation

```bibtex
@misc{nussbaum2024nomic,
    title={Nomic Embed: Training a Reproducible Long Context Text Embedder},
    author={Zach Nussbaum and John X. Morris and Brandon Duderstadt and Andriy Mulyar},
    year={2024},
    eprint={2402.01613},
    archivePrefix={arXiv},
    primaryClass={cs.CL}
}
```

## Original Source

All models are published at [huggingface.co/nomic-ai](https://huggingface.co/nomic-ai). FastEmbed
6.0.2 selects `nomic-embed-vision-v1.5` as the cache repository behind the-one-mcp's default image
model; exact runtime files are recorded in `models-manifest.toml`.
