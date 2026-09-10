# intfloat Models (Multilingual E5)

## Models

| Model | Dims | Size | Multilingual | Hugging Face |
|-------|------|------|-------------|-------------|
| multilingual-e5-small | 384 | ~45MB | Yes (100+ languages) | [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) |
| multilingual-e5-base | 768 | ~90MB | Yes (100+ languages) | [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base) |
| multilingual-e5-large | 1024 | ~220MB | Yes (100+ languages) | [intfloat/multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large) |

## Original-model license

MIT License

## Conversion/cache-repository license and provenance

The original intfloat model weights are MIT licensed. The Qdrant ONNX conversion selected for
`multilingual-e5-large` declares Apache-2.0 and is recorded as a distinct cache-repository license
in `models-manifest.toml`; the small and base cache repositories are the original intfloat repos.

## Authors

Microsoft Research (intfloat)

## Citation

```bibtex
@article{wang2024multilingual,
    title={Multilingual E5 Text Embeddings: A Technical Report},
    author={Liang Wang and Nan Yang and Xiaolong Huang and Linjun Yang and Rangan Majumder and Furu Wei},
    year={2024},
    eprint={2402.05672},
    archivePrefix={arXiv},
    primaryClass={cs.CL}
}
```

## Original Source

All models originally published at [huggingface.co/intfloat](https://huggingface.co/intfloat).
The exact ONNX repositories and paths recorded in `models-manifest.toml` are selected and consumed
by FastEmbed 6.0.2; this repository does not assert who produced those exports.
