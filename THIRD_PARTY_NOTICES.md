# Third-party components

This project integrates or supports the following components. Their upstream license files
remain authoritative and must be included when redistributing bundled code or model weights.

| Component | Purpose | Upstream | License |
|---|---|---|---|
| faster-whisper | Local speech-to-text adapter | https://github.com/SYSTRAN/faster-whisper | MIT |
| CTranslate2 | Inference runtime used by faster-whisper | https://github.com/OpenNMT/CTranslate2 | MIT |
| Whisper models/code | Speech recognition models | https://github.com/openai/whisper | MIT |
| Ollama | Optional local LLM runtime | https://github.com/ollama/ollama | MIT |
| Qwen3-4B-GGUF | Optional local protocol model | https://huggingface.co/Qwen/Qwen3-4B-GGUF | Apache-2.0 |

Gemini is accessed as an external API and is not redistributed with this repository.
