# Qdrant-hosted FastEmbed Models

These cache repositories are ONNX conversions selected directly by FastEmbed 6.0.2. Attribution
to the original model remains with the upstream authors.

| Model | Type | Dims | Cache-repository license | Cache repository / original source |
|-------|------|------|--------------------------------------|------------------------------------|
| clip-ViT-B-32-vision | Image | 512 | MIT | [Qdrant cache](https://huggingface.co/Qdrant/clip-ViT-B-32-vision) / [OpenAI CLIP](https://github.com/openai/CLIP) |
| resnet50-onnx | Image | 2048 | Apache-2.0 | [Qdrant cache](https://huggingface.co/Qdrant/resnet50-onnx) / [Microsoft ResNet-50](https://huggingface.co/microsoft/resnet-50) |
| Unicom-ViT-B-16 | Image | 768 | Apache-2.0 | [Qdrant cache](https://huggingface.co/Qdrant/Unicom-ViT-B-16) / [Unicom paper](https://arxiv.org/abs/2304.05884) |
| Unicom-ViT-B-32 | Image | 512 | Apache-2.0 | [Qdrant cache](https://huggingface.co/Qdrant/Unicom-ViT-B-32) / [Unicom paper](https://arxiv.org/abs/2304.05884) |
| Splade_PP_en_v1 | Sparse text | 0 | Apache-2.0 | [Qdrant cache](https://huggingface.co/Qdrant/Splade_PP_en_v1) / [prithivida source](https://huggingface.co/prithivida/Splade_PP_en_v1) |

The canonical model cards remain authoritative for current license metadata, authorship,
intended use, and citations. Exact runtime paths and FastEmbed variants are recorded in
`models-manifest.toml`. The license identifiers in the table are metadata, not a claim that a
generic local license copy is the exact text for every component.

## License boundary

The Qdrant BGE, multilingual-E5, ResNet-50, Unicom, and Splade conversion/cache repositories in
this manifest declare Apache-2.0; the Qdrant CLIP cache declares MIT. The original models remain
under their own licenses: OpenAI CLIP is MIT; Microsoft ResNet-50, DeepGlint Unicom, and
Splade_PP_en_v1 are Apache-2.0. `models-manifest.toml` records both repositories and both license
fields so a conversion license is never presented as relicensing the original model.

Before any publication, recover and audit the exact upstream license, copyright, and notice texts
for every canonical Qdrant cache repository and every corresponding original-model repository.
No unverified generic license copy is substituted for those repository-specific materials.
