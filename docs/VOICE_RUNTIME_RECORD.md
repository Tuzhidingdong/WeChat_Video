# Personal English voice runtime record (Slice A)

This file records the verified local runtime and model provenance. It contains no
private voice data, raw recording, speaker embedding, or user-specific absolute paths.

## Runtime

Created with conda at project-local `.venv-voice` (no global Python/PATH change):

- Python 3.9.23
- torch 2.1.2+cpu, torchaudio 2.1.2+cpu
- numpy 1.26.4, scipy 1.13.1
- librosa 0.9.1, numba 0.60.0, soundfile 0.13.1
- whisper-timestamped 1.14.2, openai-whisper 20250625 (import only; CUDA Whisper branch disabled)
- transformers 4.27.4, tokenizers 0.13.3, huggingface-hub 0.36.2, cached_path 1.8.10
- OpenVoice source: `tools/openvoice-src` (myshell-ai/OpenVoice, MIT)
- MeloTTS source: `tools/melotts-src` (myshell-ai/MeloTTS)

Pinned versions are in `requirements-voice.txt`.

## Models (verified against upstream SHA-256)

| Model | Local path | Source | SHA-256 |
|---|---|---|---|
| OpenVoice V2 converter | `tools/openvoice/checkpoints_v2/converter/checkpoint.pth` | `myshell-ai/OpenVoiceV2` | `9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e` |
| OpenVoice EN-US source SE | `tools/openvoice/checkpoints_v2/base_speakers/ses/en-us.pth` | `myshell-ai/OpenVoiceV2` | `0d092d4af0815a4bfbc6105b65621ab68dc4c61b2f55044d8a66968a34947c32` |
| MeloTTS EN base | `assets/models/melo-en-us/checkpoint.pth` | `myshell-ai/MeloTTS-English` | `acd278040eaf9536908e2b965273df5a731c44d8f0da66cc5fed7972772ed23c` |

Silero VAD is cached under `.cache/torch/hub` from `snakers4/silero-vad` and used
through an offline energy-based segmentation path. The official converter watermark
(`@MyShell`) is preserved in every converted WAV.

## Voice profile

Stored only at `private/voice_profile/` and ignored by Git. Metadata records a
fingerprint derived from the reference audio hash plus the model revision; daily
generation reuses `target_se.pth` and never re-extracts the embedding.
