# One-time personal voice profile for English (US) narration

**Decision:** Use the user's own authorized voice as the recurring tone color, while pronunciation and linguistic content come from a standard US-English base TTS voice. The user records once during enrollment; daily video generation must not ask for another recording.

**Implementation target:** Milestone 1 — Slice A refinement only.  
**Frozen authority:** TASK_PLAN.md V5 is unchanged. This plan does not authorize Slice B, Milestone 2, or Milestone 3.

## 1. User-selected output

The user selected: **preserve my voice timbre, but speak standard American English.**

Interpretation:
- The reference recording supplies the user's speaker/tone-color identity.
- The English-US base TTS supplies US-English phonemes and pronunciation.
- OpenVoice transfers the target voice color onto the English-US base speech.
- Do not attempt to imitate the user's Chinese accent when generating English.
- This is a zero-shot voice-profile workflow, not model fine-tuning and not a promise of a perfect identity match. Similarity, intelligibility, and prosody must be judged from a local listening sample.

## 2. Selected architecture: MeloTTS EN-US + OpenVoice V2

Use the official OpenVoice V2 two-stage flow demonstrated in the upstream demo_part3.ipynb:

1. **Base speech generation:** MeloTTS TTS(language="EN", device="cpu"); explicitly select the EN-US speaker ID. This controls US-English pronunciation.
2. **Target voice enrollment:** use the user's own reference recording once, then extract a target speaker/tone-color embedding using OpenVoice V2 se_extractor.get_se(reference_audio, tone_color_converter, vad=True).
3. **Voice conversion:** load the matching MeloTTS base speaker embedding checkpoints_v2/base_speakers/ses/en-us.pth as src_se; load the user's saved embedding as tgt_se; call ToneColorConverter.convert(..., src_se=..., tgt_se=..., output_path=...).
4. Store the user's target_se in the private project-local voice profile. Daily runs load this embedding; they must not call speaker extraction again.
5. Keep the official converter watermark/message behavior. Do not strip, bypass, or alter model watermarking.

The reference audio may be in the user's natural language; it does not need to be an English performance. A natural Mandarin recording is acceptable for capturing tone color. English pronunciation comes from the selected EN-US base speaker. Avoid reading English with a forced accent just to create the reference.

### Why not Piper as the primary voice path?

The previously proposed Piper Lessac model produces its own voice. It does not by itself preserve the user's timbre. The official OpenVoice V2 demonstration pairs MeloTTS base speakers with the OpenVoice tone-color converter. Therefore the earlier Piper-as-primary instruction is superseded by this plan. Keep any already-downloaded Piper model only if useful for diagnostics; do not make it the user's daily voice.

## 3. One-time user voice enrollment

Create a dedicated one-time command such as Register_My_Voice.bat.

Expected local input:

    private/
      voice_profile/
        reference_input.wav
        target_se.pth
        voice_profile.json
        enrollment.log

The user performs a one-time recording and places it at private/voice_profile/reference_input.wav. The registration command:
- validates the audio and converts it using project-local FFmpeg if necessary;
- checks speech duration, clipping, sample rate, channel count, silence, and noise floor;
- extracts the embedding once;
- saves target_se.pth and metadata;
- generates a short English-US comparison sample with the user's converted voice;
- marks the profile ready only after real extraction and conversion succeed.

Recommended recording guidance (project recommendation, not a model minimum):
- Approximately 2–3 minutes of continuous natural speech.
- Use the user's natural speaking language and normal conversational voice.
- Quiet room, one microphone position, stable distance, no music, no echo/reverb, and no background conversation.
- Avoid whispering, shouting, acting, and exaggerated emotional changes.
- A mono WAV is preferred. If supplied audio is MP3/M4A/stereo, convert locally with the project FFmpeg; do not upload it to a service.

A recording prompt should contain varied but ordinary sentences and enough uninterrupted speech. It must not ask the user to mimic an American accent. The purpose is to capture the speaker's timbre, not their English pronunciation.

The registration tool must be idempotent:
- If a valid profile already exists, show its fingerprint and ask before replacing it.
- Never overwrite a valid profile silently.
- A new recording is needed only when the user chooses to replace/update the voice profile.

## 4. Private storage and data protection

All voice data is private user content and must remain on this PC.

- Add private/voice_profile/ and temporary voice-processing directories to .gitignore.
- Never commit, push, attach to issues/PRs, or include in GitHub Actions: raw recordings, speaker embeddings, generated clone previews, or voice-profile metadata containing local paths.
- Never send voice data to OpenVoice cloud demos, Hugging Face Spaces, external APIs, telemetry, or any remote service.
- Do not print raw transcript/audio, personal file names, or embedding contents in logs.
- Do not place voice files in normal outputs/<run> review packages. Store only non-sensitive model/profile IDs and processing status in review reports.
- Keep the reference WAV locally so the user can regenerate the embedding; the user may delete it after confirming the profile, but that prevents future re-enrollment without another recording.
- Daily runtime must work with network disabled after setup and profile enrollment.

The voice is the user's own. Do not provide a mechanism to enroll another person's voice without that person's explicit authorization.

## 5. Project-local runtime isolation

The existing Slice A environment is Python 3.12.4 and must remain intact. The upstream OpenVoice installation instructions demonstrate a Python 3.9 environment and use older dependencies (including NumPy 1.22.0 and librosa 0.9.1). Do not blindly add those dependencies to the existing Manim .venv.

Before implementation:
1. Check the upstream OpenVoice and MeloTTS requirements and model files.
2. Attempt a small, isolated Windows CPU compatibility proof.
3. Prefer a separate project-local voice runtime such as .venv-voice based on a compatible Python 3.9.x interpreter. If no compatible interpreter exists, install/download a Python runtime under this project's tools/ only; do not modify global Python, PATH, registry, or another project's environment.
4. Pin the exact working versions of Python, PyTorch CPU, torchaudio, MeloTTS, OpenVoice, and supporting packages in a dedicated voice-runtime requirements/lock file.
5. Do not install Gradio, OpenAI clients, web apps, or unrelated optional dependencies if the CLI does not use them.
6. Set Hugging Face, Torch, pip, temporary, and cache directories to project-local paths for setup and runtime processes.
7. Keep the main .venv and Manim dependency versions untouched.

The official OpenVoice usage page describes its standard install path as Linux-focused and points to community-contributed guides for other platforms. Windows CPU support is therefore a verification gate, not an assumption. If the isolated Windows CPU proof fails, stop and report the precise blocker rather than changing the main environment or silently switching voice models.

## 6. Model files and local paths

All model and checkpoint downloads must remain under the project, for example:

    tools/
      openvoice/
        checkpoints_v2/
          converter/
          base_speakers/
            ses/
    assets/
      models/
        melo-en-us/
    private/
      voice_profile/
        reference_input.wav
        target_se.pth
        voice_profile.json

Use the exact official checkpoint assets and MeloTTS English base model expected by the selected OpenVoice V2 demo. Verify download sizes and published checksums where available; record source URLs, model revisions, license notices, and local SHA-256 values.

Do not assume that a third-party Piper ONNX voice is interchangeable with the OpenVoice V2 MeloTTS base speaker. The EN-US source speaker embedding and base model must match the same MeloTTS checkpoint/version.

## 7. Daily generation pipeline

    English script
        -> MeloTTS EN-US base WAV
        -> OpenVoice V2 tone-color conversion using saved target_se
        -> final per-unit English WAV
        -> measured sample-count timeline
        -> Manim cue synchronization
        -> FFmpeg final assembly

Requirements:
- Reuse the saved user embedding for every speech unit.
- Do not require the user to record again.
- Generate each speech unit and pronunciation-review asset with the same selected profile.
- Keep the current V5 global timeline, cover, pauses, cue checkpoints, loudness normalization, and QA behavior.
- Perform speaker conversion before timeline sample-count measurement; the converted output WAV, not the base MeloTTS WAV, is authoritative for timing.
- Never time-stretch or change playback speed merely to force the 55–65 second duration.
- The pipeline must fail closed if the user's profile is missing, corrupt, incompatible with the checkpoint version, or fails conversion. Do not silently fall back to Piper or an anonymous MeloTTS speaker.
- Include an explicit profile fingerprint/model revision in the run manifest without exposing the raw voice or embedding.

## 8. Required proof before enabling as the default

### Stage A — Windows CPU feasibility
- Build the isolated runtime without changing the existing Slice A .venv.
- Load OpenVoice V2 converter checkpoints on CPU.
- Load MeloTTS EN-US and generate a short base WAV.
- Convert the WAV using a controlled test reference.
- Confirm non-empty, intelligible output and measure processing time / real-time factor.
- Use an authorized upstream demo reference asset only for technical integration testing; do not represent it as the user's voice.
- Verify all model/cache paths stay inside the project.

### Stage B — User profile enrollment
- Wait for the user to provide their one-time reference recording.
- Extract and persist the target embedding.
- Generate two otherwise identical short English-US samples: base MeloTTS and user-voice-converted output.
- Report speaker-profile creation success and allow the user to listen.
- Do not claim the output matches the user's voice until the user confirms it.

### Stage C — Full Slice A integration
- Generate all English speech units through the saved profile.
- Confirm all output is English and pronunciation follows the EN-US base model.
- Validate the converted WAV sample counts and timing.
- Render the updated centered, non-stacking Manim scene.
- Produce a new full MP4 and QA report.
- The user performs final listening/playback acceptance.

## 9. Acceptance and fallback

- Primary target: user timbre + clear, intelligible US-English pronunciation.
- User voice profile creation happens once; daily use reuses the saved embedding.
- English pronunciation quality, speaker similarity, CPU performance, and long-form stability must be tested on this Windows machine.
- If the voice is intelligible but similarity is weak, report that accurately and offer a new enrollment recording only with user approval.
- If OpenVoice cannot run reliably on local Windows CPU, preserve all existing work and stop for a decision. Do not silently use online TTS, a paid API, or a generic voice as if it were the user's voice.
- The Chinese sherpa/MeloTTS model and the existing Piper test option, if present, remain untouched until the user accepts the personal voice pipeline.

## 10. Upstream references

- OpenVoice V2 repository and MIT license: https://github.com/myshell-ai/OpenVoice
- Official OpenVoice V2 MeloTTS + converter + reference speaker example: https://github.com/myshell-ai/OpenVoice/blob/main/demo_part3.ipynb
- Official install / platform notes: https://github.com/myshell-ai/OpenVoice/blob/main/docs/USAGE.md
- MeloTTS English-US support and CPU usage notes: https://github.com/myshell-ai/MeloTTS
- MeloTTS installation and English speaker selection: https://github.com/myshell-ai/MeloTTS/blob/main/docs/install.md

**Important:** The OpenVoice V2 pipeline and model availability are upstream facts; Windows Python 3.9 CPU feasibility and output quality must be measured locally before this becomes the daily default.
