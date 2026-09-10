# EmbeddingGemma Models

## Models

| Model | Dims | FastEmbed cache repository |
|-------|------|----------------------------|
| EmbeddingGemma 300M | 768 | [onnx-community/embeddinggemma-300m-ONNX](https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX) |

FastEmbed 6.0.2 declares 768 output dimensions and consumes the full-precision, Q4, and quantized
ONNX graphs plus their external-data files from this single cache repository.

## Original-model license and terms

The model repository declares the custom `gemma` license. Redistribution and use are governed by
the canonical [Gemma terms](https://ai.google.dev/gemma/terms); they are not replaced or
relicensed by this repository. Review the current terms before preparing or publishing an asset.

## Conversion/cache-repository license and provenance

The original model repository is `google/embeddinggemma-300m`; FastEmbed selects the separately
converted `onnx-community/embeddinggemma-300m-ONNX` cache repository. The schema records both
provenance layers and their Gemma license marker explicitly.

## Authors and provenance

EmbeddingGemma is published by Google DeepMind; the ONNX conversion is published by the
Hugging Face ONNX Community. The upstream model card is the authoritative source for authorship,
intended use, limitations, safety information, and citations.
