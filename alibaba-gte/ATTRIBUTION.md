# Alibaba GTE Models

## Models

| Model | Dims | Size | Hugging Face |
|-------|------|------|-------------|
| gte-base-en-v1.5 | 768 | ~50MB | [Alibaba-NLP/gte-base-en-v1.5](https://huggingface.co/Alibaba-NLP/gte-base-en-v1.5) |
| gte-large-en-v1.5 | 1024 | ~130MB | [Alibaba-NLP/gte-large-en-v1.5](https://huggingface.co/Alibaba-NLP/gte-large-en-v1.5) |

Each FastEmbed 6.0.2 cache repository contains both full-precision and quantized variants. The
legacy `fastembed-v4` archives contain only the full-precision ONNX file, so both archives are
explicitly marked `refresh-required` in `models-manifest.toml`.

## Original-model and cache-repository license

The original models and the exact Alibaba-NLP cache repositories selected by FastEmbed declare
the MIT License. Both provenance layers are recorded explicitly in `models-manifest.toml`.

## Authors

Alibaba DAMO Academy — [damo.alibaba.com](https://damo.alibaba.com/)

## Citation

```bibtex
@misc{li2023towards,
    title={Towards General Text Embeddings with Multi-stage Contrastive Learning},
    author={Zehan Li and Xin Zhang and Yanzhao Zhang and Dingkun Long and Pengjun Xie and Meishan Zhang},
    year={2023},
    eprint={2308.03281},
    archivePrefix={arXiv},
    primaryClass={cs.CL}
}
```

## Original Source

All models and ONNX files are published at
[huggingface.co/Alibaba-NLP](https://huggingface.co/Alibaba-NLP). FastEmbed 6.0.2's exact runtime
paths are recorded in `models-manifest.toml`.
