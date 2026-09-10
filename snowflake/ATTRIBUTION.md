# Snowflake Arctic Embed Models

## Models

| Model | Dims | FastEmbed cache repository |
|-------|------|----------------------------|
| snowflake-arctic-embed-m | 768 | [Snowflake/snowflake-arctic-embed-m](https://huggingface.co/Snowflake/snowflake-arctic-embed-m) |

The artifact group includes the full-precision and quantized ONNX files selected by FastEmbed
6.0.2.

## Original-model and cache-repository license

[Apache License 2.0](../nomic-ai/LICENSE), as declared by the upstream model repository. See the
canonical model card for its current license metadata, usage guidance, and citations.

The exact Snowflake repository serves as both the original-model and FastEmbed cache provenance;
the two schema fields are intentionally equal rather than conflated.

## Cache provenance

The exact FastEmbed variants and required runtime paths are recorded in `models-manifest.toml`.
If this artifact is eventually published, redistribution is conditional on checksum verification
and the separate publication-time license/copyright/notice audit; no Snowflake archive is
currently redistributed by the planned v6 release.
