# Slice A refinement: English narration, centered framing, and clean visual stages

**Status:** Authorized implementation refinement based on the user's first local playback review  
**Authority:** Frozen `TASK_PLAN.md` V5 remains unchanged. This document does not authorize Slice B, Milestone 2, or Milestone 3.  
**Target:** `feat/slice-a-english-visual-refinement`

## 1. User-observed problems

The first rendered sample exposed three user-facing problems:

1. Mandarin TTS pronunciation was unnatural.
2. The composition appeared offset / poorly framed.
3. New equations appeared before earlier equations had been removed, causing visual stacking.

The next sample must address all three in the actual rendering path, not just change documentation or the preview script.

## 2. English-only video output

For the current Slice A sample, switch the spoken and visible video language to **English (US)**.

- Use `content/sample_script.en.json` as the new default Slice A script after the TTS adapter is migrated and tests pass.
- Set `language` to `en-US`.
- For every speech unit, `raw_text`, `display_text`, and `spoken_text` must all be English. There must be no Chinese narration or Chinese captions.
- Translate all user-visible Manim text: cover, scene headings, plot labels, annotations, explanatory text, and caveats.
- English SRT and ASS subtitles must match the English narration and use a Latin-script font.
- The formulas retain their scientific symbols and notation; do not translate or alter the science to make the English easier.
- Keep the original Fact Card and source records as the scientific evidence authority. Do not rewrite or weaken claims, assumptions, sign conventions, or source status merely to make the English script fit.
- The review audio must also be English and cover the technical terms listed in the English script.

### TTS and personal voice choice

The user selected: **preserve the user's own voice timbre while speaking standard US English**. Use the official OpenVoice V2 two-stage architecture, not Piper as the primary voice:

- Base English voice: MeloTTS with the explicit EN-US speaker ID. This is responsible for US-English pronunciation.
- Personal timbre: OpenVoice V2 ToneColorConverter, driven by a target speaker embedding extracted once from the user's own natural reference recording.
- Enrollment: use se_extractor.get_se(reference_audio, tone_color_converter, vad=True), then persist the returned target embedding as a private local profile. A natural Mandarin recording is acceptable; the user must not perform an American accent.
- Daily generation: generate each English speech unit through MeloTTS EN-US, then convert it using the saved user embedding. Do not re-extract the profile on every run.
- Retain the official OpenVoice V2 watermark/message behavior. Do not strip or bypass it.
- Keep the workflow local, CPU-only, and offline after initial model setup. No Edge TTS, network TTS fallback, paid APIs, or extra subscriptions.
- Do not delete the existing sherpa/MeloTTS Chinese model. Do not use Piper Lessac as the daily personal voice. The earlier Piper proposal is superseded by docs/VOICE_PROFILE_ENGLISH_PLAN.md.
- Voice similarity and US pronunciation are targets, not guarantees. Require a user listening approval before calling this the user's accepted voice.
- OpenVoice's standard install documentation is Linux-focused and Windows platform guidance is community-contributed. Verify Windows CPU compatibility in an isolated project-local runtime before changing the daily pipeline.
- Keep raw voice recordings, speaker embeddings, and clone previews under ignored private/voice_profile/; never commit or upload them.

Detailed architecture, one-time enrollment, runtime isolation, model files, CPU feasibility gates, and privacy rules: docs/VOICE_PROFILE_ENGLISH_PLAN.md.

Official references:
- https://github.com/myshell-ai/OpenVoice
- https://github.com/myshell-ai/OpenVoice/blob/main/demo_part3.ipynb
- https://github.com/myshell-ai/OpenVoice/blob/main/docs/USAGE.md
- https://github.com/myshell-ai/MeloTTS

## 3. Correct the framing without violating the safe zones

The current layout reserves 5% on the left but 15% on the right, while scene objects are manually placed around x = -0.45. This makes the composition intentionally left-shifted relative to the full video frame. The next sample should look visually centered to a viewer.

- Keep the 9:16, 1080×1920, 30 fps canvas.
- Preserve the right-side 15% interface reserve and existing top, subtitle, and bottom reservations.
- Make the horizontal science-content column symmetric: set the left reserve to 15% as well, or derive an equally conservative symmetric content width from the stricter side. For a 9-unit-wide frame and 15% margins, the usable content width is 6.3 units.
- Place the center of the main scientific composition at x = 0. Do not retain arbitrary `-0.45`, `-0.55`, or other manual horizontal offsets.
- Derive positions, maximum widths, and scales from the actual frame and safe-zone profile. Do not scatter unrelated hard-coded coordinates throughout the scene.
- Vertically center the main stage within the 10%–68% science-content band. Keep subtitles in the dedicated 68%–78% band and preserve the 78%–100% bottom interface reserve.
- Keep the camera static for this Slice A template. Explicitly set/verify the 9×16 camera frame; do not add unrequested camera pans or zooms. The issue is composition and scale, not a cinematic lens effect.
- The title, particle illustration, plot, equations, and annotations must all remain inside the safe content bounds. If a group is too wide, scale/reflow the group as a whole rather than shifting it sideways.

The visual check must use actual rendered frames or the generated MP4, not just bounding-box calculations.

## 4. Replace stacked formulas with mutually exclusive visual stages

The current scene calls `FadeIn` for later objects but leaves earlier formulas and notes in the scene. This is the direct cause of the stacking reported by the user.

Refactor the Manim scene so that each cue checkpoint selects one complete visual stage.

Mandatory behavior:

1. Every stage owns one named `VGroup` (or equivalent) containing all objects for that stage.
2. When the next checkpoint begins, animate the previous stage out and the next stage in. Use a clear `FadeOut(previous_stage) + FadeIn(next_stage)` or a properly tested `ReplacementTransform`.
3. After a transition, the previous stage must no longer be present in the scene. No stale formula, annotation, or graph label may remain unless it is deliberately part of the new stage.
4. Do not independently `FadeIn` a new formula while leaving the previous formula on screen.
5. Avoid rebuilding duplicate axes/curves when a later stage intentionally reuses the same graph. In that case create a single explicitly owned graph stage and update it deterministically.
6. Use the measured global cue start/end times. The transition starts at the cue's `start_ms`, consumes a bounded transition duration, and the new stage holds until the next cue. Do not let a chain of Manim `play` calls extend beyond the cue or drift the global timeline.
7. Preserve the explicit 0–1000 ms cover and first narration at/after 1000 ms.
8. Emit a `visual_stage_manifest.json` with each cue, stage ID, transition start/end frame, and the single active stage ID. This supports review and timing QA.

### Visual-first sequence

Keep the existing single critical-nucleus template; do not add another template family. Make the sequence more explanatory and less like a stack of equations:

| Trigger | Visual stage | On-screen content |
|---|---|---|
| `INTRO_QUESTION` | Particle/nucleus illustration | A small particle cluster appears; show the idea of an unstable tiny embryo with a clean visual metaphor. |
| `SHOW_TOTAL_FREE_ENERGY` | Energy competition | One total free-energy equation only, with the surface and bulk terms visually distinguished. Do not display two independent equations simultaneously. |
| `SHOW_SCALING` | Area versus volume | A simple visual comparison of surface-area scaling (`r²`) and volume scaling (`r³`), with short English labels. |
| `SHOW_FREE_ENERGY_CURVE` | Free-energy landscape | One centered curve with readable axis labels; no leftover formulas from the previous stage. |
| `MARK_CRITICAL_RADIUS` + `COMPARE_SUB_SUPERCRITICAL` | Critical threshold | The same curve, one vertical critical-radius marker, and concise English labels for below/above the threshold. Do not duplicate the graph. |
| `SHOW_CRITICAL_RADIUS_EQUATION` | Critical-radius relation | Show only `r* = 2γ / Δg_v` as the main equation, with a small explanatory label. |
| `SHOW_BARRIER_EQUATION` | Barrier relation | Show only `ΔG* = 16πγ³ / (3Δg_v²)` as the main equation. |
| `MODEL_LIMITS` | Model assumptions | Transition to English text describing the spherical, homogeneous, isotropic-interface assumptions and real-system limitations. No previous formula remains. |

The particle/nucleus graphic is an explanatory illustration, not a claim of a specific atomistic pathway. Keep the scientific assumptions and limitations visible in the Fact Card and review package.

## 5. Script duration and pacing

- The supplied English script targets 55–65 seconds, but the measured WAV duration is authoritative.
- Re-run TTS and inspect actual speech-unit sample counts.
- If the real voice output is shorter than 55 seconds, revise the English narration only by adding scientifically supported, useful explanation linked to existing claim IDs. Do not add filler, artificial silence, slow-motion, time stretching, or altered playback speed.
- If it exceeds 65 seconds, tighten wording without dropping claim coverage or model caveats.
- Do not falsify the QA result. A sample outside the target duration must remain a warning/failure according to the current V5 acceptance rule.

## 6. Required implementation updates

The local Agent must integrate these decisions with the newer local-only work already present in `E:\Agent\WeChat\Video`:

- OpenVoice V2 + MeloTTS EN-US setup, validation, CPU inference, one-time personal voice enrollment, and pronunciation review.
- English default script selection.
- English font detection and ASS subtitle configuration.
- English-only output validation.
- Centered content geometry and camera/safe-zone assertions.
- Explicit visual-stage transition logic and stage manifest.
- QA/manual-review text updated from Mandarin/Chinese to English.
- README and status documentation updated without changing frozen `TASK_PLAN.md`.
- Keep project-local portable MiKTeX, FFmpeg/ffprobe configuration, previous media compatibility fixes, local test coverage, and the existing Chinese model.

## 7. Required tests and evidence

Before reporting success, the Agent must execute real tests in the Windows project workspace:

1. JSON/schema validation for the English script and all claim links.
2. Unit tests verifying all user-visible script/caption fields contain no CJK characters.
3. Isolated Windows CPU feasibility test for OpenVoice V2 + MeloTTS EN-US, without modifying the existing Manim .venv.
4. Real MeloTTS EN-US inference and OpenVoice tone-color conversion; after the user provides a recording, extract and reuse the saved private target embedding.
5. WAV sample-rate/channel/frame-count validation and measured 55–65 second duration check.
6. Manim render with the actual 1080×1920 project configuration and portable MiKTeX.
7. Visual-stage manifest assertions: each checkpoint has exactly one active stage; the prior stage is removed before/when the next stage is displayed; no duplicate stage/graph IDs.
8. Safe-zone checks for every stage and rendered-frame visual review at intro, each transition, graph, critical-radius equation, barrier equation, and final caveat.
9. FFmpeg assembly and ffprobe verification.
10. Full QA report and a new real MP4.

A code-only test or a synthetic FFmpeg smoke clip does not prove the scene is visually fixed. The Agent must generate and inspect the actual English sample. The user performs the final playback acceptance.

## 8. Local synchronization and preservation guard

The local workspace contains important uncommitted work from the previous installation/testing pass, including portable-tool integration, TTS/model configuration, tests, and media fixes. **Do not overwrite it.**

Before syncing this branch:

- Capture `git status --short`, `git diff`, and untracked source-file inventory.
- Back up tracked diffs and relevant untracked source/config/test files inside a project-local backup folder. Do not copy ignored `.venv`, portable tools, models, or large output media.
- Fetch this refinement branch.
- Preserve and reapply the user's existing local changes deliberately; reconcile overlapping files rather than using `git reset --hard`, `git clean`, or blind `git pull`.
- Keep `config/tools.local.json`, `tools/`, `assets/models/`, `.venv/`, and existing outputs intact.
- Keep the previous Chinese model in place. Add the English model as a separate project-local asset; do not redownload the existing Chinese model.

## 9. Scope and release boundary

- Do not modify or unfreeze `TASK_PLAN.md`.
- Do not modify `main`, merge a PR, or start Slice B.
- Do not touch `WeChat_control`, its browser profile, account settings, or Skills.
- No Edge/CDP, upload, scheduling, publishing, or final-send actions.
- No paid API, online TTS, paid Flow credits, or OpenCode Go Extra Usage.
- The Fact Card remains `DRAFT_PENDING_USER_REVIEW`; the output remains `NOT_FOR_PUBLICATION_PENDING_USER_FACT_CARD_REVIEW`.
- The Agent may render an internal development sample for verification, but must not claim final user acceptance.

## 10. Completion report

Report the exact commit/branch, files changed, model source/license, model and voice configuration, measured English TTS timings, test commands/results, stage-manifest evidence, rendered MP4 path and SHA-256, QA warnings, and unresolved user-review items. Stop after the new sample is generated and ready for the user's playback review.
