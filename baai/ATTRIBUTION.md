# BAAI Models

## Models

### Embedding Models

| Model | Dims | Size | Hugging Face |
|-------|------|------|-------------|
| BGE-small-en-v1.5 | 384 | ~24MB | [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) |
| BGE-base-en-v1.5 | 768 | ~50MB | [BAAI/bge-base-en-v1.5](https://huggingface.co/BAAI/bge-base-en-v1.5) |
| BGE-large-en-v1.5 | 1024 | ~130MB | [BAAI/bge-large-en-v1.5](https://huggingface.co/BAAI/bge-large-en-v1.5) |
| BGE-small-zh-v1.5 | 512 | See manifest | [BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5) |
| BGE-large-zh-v1.5 | 1024 | See manifest | [BAAI/bge-large-zh-v1.5](https://huggingface.co/BAAI/bge-large-zh-v1.5) |
| BGE-M3 dense embedding | 1024 | See manifest | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) |
| BGE-M3 sparse output | 0 (not a dense vector) | See manifest | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) |

### Reranker Models

| Model | Hugging Face |
|-------|-------------|
| BGE-reranker-base | [BAAI/bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base) |
| BGE-reranker-v2-m3 (original) | [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| BGE-reranker-v2-m3 (FastEmbed ONNX cache) | [rozgo/bge-reranker-v2-m3](https://huggingface.co/rozgo/bge-reranker-v2-m3) |

## Original-model license

See each model's official source page and `models-manifest.toml`. In particular,
BAAI/bge-reranker-v2-m3 declares Apache-2.0; do not infer one license for the entire BAAI family.

## Conversion/cache-repository license and provenance

Licensing is resolved per original model and per exact cache/conversion repository; one BAAI-family
license does not apply automatically to every record.

For BGE-reranker-v2-m3, FastEmbed selects
[`rozgo/bge-reranker-v2-m3`](https://huggingface.co/rozgo/bge-reranker-v2-m3), an ONNX export of the
original [`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3). The official
BAAI source page declares Apache-2.0 for the original model. The official Rozgo cache page declares
no license metadata. Therefore the conversion/cache-repository license is unresolved and must be
recorded as `NOASSERTION`; redistribution of that cache artifact remains blocked until its rights
are established independently. The original model's Apache-2.0 declaration does not supply a
license for the separate Rozgo export.

Other BAAI-family records retain the licenses declared by their own official source and selected
cache pages. FastEmbed also selects Xenova and Qdrant ONNX conversion repositories, whose
conversion licenses are recorded separately from original-model licenses in
`models-manifest.toml`. Neither provenance layer substitutes for the other.

## Authors

Beijing Academy of Artificial Intelligence (BAAI)

## Citation

```bibtex
@misc{bge_embedding,
    title={C-Pack: Packaged Resources To Advance General Chinese Embedding},
    author={Shitao Xiao and Zheng Liu and Peitian Zhang and Niklas Muennighoff},
    year={2023},
    eprint={2309.07597},
    archivePrefix={arXiv},
    primaryClass={cs.CL}
}
```

## Original Source

The original models are published by [BAAI](https://huggingface.co/BAAI). The exact ONNX cache
repositories selected by FastEmbed 6.0.2, including Qdrant/Xenova conversions and BGE-M3's
shared dense/sparse artifact group, are recorded in `models-manifest.toml`.
