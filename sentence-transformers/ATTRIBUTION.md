# Sentence-Transformers Models

## Models

| Model | Dims | Size | Hugging Face |
|-------|------|------|-------------|
| all-MiniLM-L6-v2 | 384 | ~23MB | [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) |
| all-MiniLM-L12-v2 | 384 | ~33MB | [sentence-transformers/all-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L12-v2) |
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | ~45MB | [sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) |
| all-mpnet-base-v2 | 768 | See manifest | [sentence-transformers/all-mpnet-base-v2](https://huggingface.co/sentence-transformers/all-mpnet-base-v2) |
| paraphrase-multilingual-mpnet-base-v2 | 768 | See manifest | [sentence-transformers/paraphrase-multilingual-mpnet-base-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2) |

## Original-model license

Apache License 2.0

## Conversion/cache-repository license and provenance

FastEmbed 6.0.2 selects Qdrant, Xenova, or Qdrant-quantized ONNX cache repositories rather than
the original training repositories. `models-manifest.toml` records the exact selected repository,
its separately audited license, and the original Sentence-Transformers repository for every
artifact group. A cache conversion does not change the original model's license or attribution.

## Authors

Nils Reimers, Iryna Gurevych — [UKP Lab, TU Darmstadt](https://www.ukp.tu-darmstadt.de/)

## Citation

```bibtex
@inproceedings{reimers-2019-sentence-bert,
    title = "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks",
    author = "Reimers, Nils and Gurevych, Iryna",
    booktitle = "Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing",
    year = "2019",
    publisher = "Association for Computational Linguistics",
    url = "https://arxiv.org/abs/1908.10084",
}
```

## Original Source

The original models are published by
[Sentence-Transformers](https://huggingface.co/sentence-transformers). The exact ONNX cache
repositories selected by FastEmbed 6.0.2, including separate quantized repositories where
applicable, are recorded in `models-manifest.toml`.
