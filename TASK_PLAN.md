# User Task Plan — daily-science-animation-bat-v5

> **Status: FROZEN — authoritative implementation baseline**
>
> Version: v5 — Cross-day runtime, camera-aware layout, deterministic rendering, and vertical-slice implementation.
>
> The user owns this document. Antigravity and workers must preserve its objective, constraints, scope, and acceptance criteria. Execution progress belongs in the sibling `STATUS.md`.
>
> **Change control:** This document is frozen. Do not silently rewrite, narrow, reinterpret, or remove requirements. Any change to the objective, scope, architecture constraints, milestone gates, or acceptance criteria requires explicit user authorization and a new versioned revision. Clarifications that do not change requirements may be recorded in `STATUS.md` with rationale.
>
> **Mandatory implementation order:**
> 1. Milestone 1 — Slice A: one complete minimal local video-production path.
> 2. Milestone 1 — Slice B: complete template library and three accepted sample videos.
> 3. Milestone 2 — independent WeChat Channels draft-upload proof.
> 4. Milestone 3 — integrated daily BAT workflow.
>
> Do not implement the entire system in one pass. Do not proceed to the next slice or milestone until the previous exit conditions have been demonstrated with evidence and accepted by the user.
>
> **Primary product behavior:** The user double-clicks one BAT file. The system creates one scientifically verified, approximately one-minute vertical video and saves it as an unpublished WeChat Channels draft. The user inspects the draft and manually clicks the final publish/send confirmation.

---

## 1. Objective

Build an independent Windows BAT-driven daily science-animation workflow for the WeChat Channels account **「成核生长」**.

### Normal daily user experience

1. The user double-clicks `Run_Daily_Video.bat`.
2. The workflow checks the local environment, configuration, persistent browser session, and unfinished job state.
3. It selects one unused topic from the human-approved Verified Topic Pool.
4. It generates a narration script, metadata, and structured storyboard using the existing OpenCode Go subscription.
5. It splits the narration into natural speech units, each linked to a subtitle cue and one or more scientific claim IDs.
6. It generates local Chinese TTS audio for each speech unit.
7. It measures the real audio durations and constructs one global timeline covering the opening cover, speech, subtitles, Manim animation, pauses, and optional Flow inserts.
8. Manim renders the scientific animation according to the timeline, cue checkpoints, camera-aware safe-zone rules, and integer frame budget.
9. FFmpeg normalizes and assembles the video segments, narration, subtitles, and optional cached Flow material.
10. The system generates a complete portrait MP4 and runs scientific, visual, audio, and technical QA.
11. If all mandatory checks pass, it uploads the video to the intended WeChat Channels account as an unpublished draft.
12. It verifies the new draft against the account's current draft list.
13. It leaves the dedicated Edge browser open at the relevant draft/review interface and displays the completion report.
14. The user inspects the video and manually clicks the final publish/send confirmation.

The user must not need to run Python commands, edit scripts or JSON files, render animations, or handle intermediate files during normal daily operation.

**The product is a one-click draft-production workflow, not an automatic publishing bot.**

### Three mandatory development milestones

**Milestone 1 — Local video-production proof**

- Slice A: prove one minimal end-to-end local video-production path using one Fact Card and one Manim template.
- Slice B: complete the other four templates, camera-aware safe-zone system, deterministic frame handling, QA, and three representative sample videos.

**Milestone 2 — Independent WeChat Channels draft-upload proof**

Prove Edge session reuse across days, browser process persistence, account identity, upload completion, draft saving, draft-list verification, login-expiry handling, and `UPLOAD_UNKNOWN` recovery. Never publish the test video.

**Milestone 3 — Integrated daily BAT workflow**

Integrate the Verified Topic Pool, Fact Card preparation, OpenCode Go, local video production, QA, kernel-level single-instance locking, cross-day Edge session reuse, and verified draft uploader into one BAT entry point.

The user must inspect and accept the three Milestone 1 sample videos before Milestone 2 begins.

---

## 2. Current state

### Existing assets and systems

- The user maintains an independent WeChat public-account automation project: `Tuzhidingdong/WeChat_control`.
- The existing public-account project must remain unchanged.
- The user has an OpenCode Go subscription and Google AI Pro subscription.
- Google Flow may provide optional visual materials using existing credits.
- The user's working environment is Windows, Python, and Edge.
- Manim Community Edition, FFmpeg, local Chinese TTS, and `gamehack/science-animation-factory` have been identified as technical references.
- `LcpMarvel/sph` and `lofe-w/opencli-social` have been identified as possible references for Channels browser automation and draft-state handling.

### Current implementation status

The complete daily video-production workflow has not yet been implemented or accepted.

Do not assume the following are already working:

- Isolated Windows Python environment for Manim.
- LaTeX installation and cached template packages.
- Offline Chinese TTS with acceptable scientific pronunciation.
- Speech-unit and subtitle timing.
- Unified audiovisual timeline.
- Manim scene-internal cue checkpoints.
- Camera-aware safe-zone validation.
- Deterministic frame budgeting and final trimming.
- FFmpeg normalization and Windows subtitle handling.
- Windows kernel-level single-instance lock.
- Cross-day Edge process and CDP session reuse.
- Reliable unpublished-draft upload.
- Complete one-click BAT workflow.

The actual active project root, Python interpreter, OpenCode CLI version, Edge executable, dedicated browser profile, installed dependencies, and login state must be inspected from the real environment.

Do not hard-code paths copied from unrelated projects or modify global Python installations unnecessarily.

---

## 3. Required outcome

### 3.1 Daily BAT workflow

Provide one main entry point:

`Run_Daily_Video.bat`

The workflow must:

1. Configure UTF-8 console and Python output.
2. Acquire a Windows kernel-level single-instance mutex.
3. Check the project-specific Python environment.
4. Check dependencies, configuration, disk space, and browser session.
5. Inspect unfinished jobs and recover only from verified safe states.
6. Select one approved topic from the Verified Topic Pool.
7. Load its approved Fact Card and source records.
8. Generate narration, metadata, and structured storyboard.
9. Validate the scientific content.
10. Split narration into speech units and subtitle cues.
11. Generate local Chinese TTS audio.
12. Measure actual audio durations and construct the global timeline.
13. Render Manim scenes with cue checkpoints and camera-aware safe zones.
14. Insert suitable cached Flow material when available.
15. Normalize and assemble all video segments.
16. Generate synchronized subtitles and narration.
17. Run mandatory scientific, layout, audio, and technical QA.
18. Reuse or initialize the dedicated Edge/CDP session safely.
19. Upload exactly one video to the intended Channels account.
20. Save it as an unpublished draft.
21. Verify the newly created draft.
22. Leave Edge open at the draft/review interface.
23. Display the result and review-package location.

If any mandatory stage fails, stop safely and report the failed stage.

The system must never upload an incomplete, unverified, or technically invalid video.

### 3.2 Verified Topic Pool and Fact Card preparation

Daily production may use only the human-approved local **Verified Topic Pool**.

New topic preparation is a separate workflow:

`Prepare_Fact_Cards.bat`

It assists with preparing batches of approximately 10–15 candidate Fact Cards per preparation cycle.

A candidate Fact Card may enter the Verified Topic Pool only after explicit human approval.

#### Source discovery order

1. Search local PDF, BibTeX, and reference libraries where available.
2. Query free scholarly metadata services such as Crossref and OpenAlex.
3. Check DOI/title/author/year consistency.
4. Retrieve available abstracts and open bibliographic content.
5. Inspect accessible full-text sources when needed to verify the specific claim.
6. Record source locations and verification status.
7. Produce a prioritized Markdown review queue.
8. Require human approval before the card enters the Verified Topic Pool.

#### Evidence status

Each claim must use one of these states:

- `FULL_TEXT_LOCATED`
- `ABSTRACT_DIRECT_SUPPORT`
- `METADATA_ONLY`
- `NEEDS_SOURCE_CHECK`
- `CONFLICTING_EVIDENCE`
- `REJECTED`

Metadata existence does not prove that a paper supports a scientific claim.

A DOI lookup, title match, or author match must not automatically mark a claim as scientifically verified.

If full text is unavailable and the abstract does not directly support the intended claim, the claim remains unverified.

Do not bypass paywalls or access restrictions.

#### Fact Card review queue

The preparation workflow must output a Markdown review list containing:

- Topic and scientific question.
- Claim count.
- Relevant source count.
- Bibliographic consistency.
- Claims directly supported by abstracts.
- Claims requiring full-text/page-level inspection.
- Contradictory or incomplete evidence.
- Suggested review priority.
- Approval status.

Sort by evidence readiness rather than invented confidence scores.

The reviewer must be able to distinguish cards needing a brief check from those requiring detailed paper inspection.

### 3.3 Scientific evidence gate

Every daily video must have an approved Fact Card recording:

- Scientific question.
- Atomic claims with stable claim IDs.
- Bibliographic references and source locators.
- Evidence type and verification state.
- Model assumptions and applicable conditions.
- Equations, variables, and units.
- Known uncertainties or competing interpretations.
- Permitted and prohibited visual representations.
- Common misconceptions.
- Human approval record.

Every speech unit and every scientifically meaningful animation action must link to one or more claim IDs.

Reject:

- Unsupported claims.
- Invented numerical values.
- Unverified equations.
- Missing or inconsistent units.
- Unsupported mechanisms.
- Animation actions contradicting the Fact Card.
- The presentation of theoretical models as universally observed mechanisms.

Distinguish clearly between:

- Experimental observations.
- Established scientific mechanisms.
- Theoretical models.
- Conceptual or schematic illustrations.

LLM self-review is not scientific verification.

If evidence is insufficient or contradictory, block the topic and select another eligible topic or stop.

### 3.4 Unified audiovisual timeline

**All components must use one global timeline whose origin is the first frame of the final MP4 at 0 ms.**

The canonical timeline file is:

`audio_timing.json`

It describes:

- Opening cover.
- Scene start/end boundaries.
- Speech-unit audio start/end boundaries.
- Subtitle cue start/end boundaries.
- Scene-relative cue checkpoints.
- Explicit silence and pause intervals.
- Visual lead-ins and tail holds.
- Optional Flow insert intervals.
- Global video frame boundaries.
- Audio sample boundaries.

No media segment may be inserted outside this timeline without rebuilding all affected timestamps.

#### Opening cover

The cover is an explicit timeline segment:

`scene_00_cover`

Initial default:

- `start_ms = 0`
- `end_ms = 1000`
- No narration.
- No subtitle cue.
- Static high-contrast title design.
- No important scientific content.

The first narration cue begins at or after the cover ends.

Do not prepend a one-second video segment after the rest of the video has been rendered.

The cover duration is configurable, but a change must trigger timeline recalculation and dependent re-rendering.

#### Speech units and subtitle cues

Storyboard hierarchy:

`Video → Scene → Speech Unit / Caption Cue`

Each speech unit has:

- `unit_id`
- `scene_id`
- `claim_ids`
- `raw_text`
- `display_text`
- `spoken_text`
- `audio_file`
- `subtitle_cue`

Each speech unit corresponds to one natural spoken phrase or short sentence and one subtitle cue.

A visual subtitle may use one or two short lines. Approximately 12–18 Chinese characters per visual line is a guideline, not a mandatory speech-unit length.

Do not split a sentence arbitrarily in the middle of a meaningful phrase.

#### Scene-internal cue checkpoints

Each Manim scene receives:

- Global scene start/end.
- Total target frame count.
- Scene-relative speech-unit start/end.
- Explicit visual trigger IDs.
- Relevant claim IDs.

Example:

```json
{
  "scene_id": "scene_02",
  "scene_start_ms": 12000,
  "scene_end_ms": 27000,
  "cue_checkpoints": [
    {
      "unit_id": "scene_02_line_01",
      "relative_start_ms": 0,
      "relative_end_ms": 4000,
      "trigger_ids": ["show_axes"]
    },
    {
      "unit_id": "scene_02_line_02",
      "relative_start_ms": 4000,
      "relative_end_ms": 10000,
      "trigger_ids": ["derive_critical_radius"]
    },
    {
      "unit_id": "scene_02_line_03",
      "relative_start_ms": 10000,
      "relative_end_ms": 15000,
      "trigger_ids": ["highlight_energy_barrier"]
    }
  ]
}
```

This is an interface example only.

The Manim template must use those checkpoints to trigger the corresponding visual actions. Do not distribute animation actions proportionally across the full scene without regard to narration.

#### Canonical timing fields

`audio_timing.json` must include at least:

- `job_id`
- `timeline_version`
- `fps`
- `sample_rate`
- `total_duration_ms`
- `cover_scene_id`
- `scene_id`
- `scene_start_ms`
- `scene_end_ms`
- `unit_id`
- `claim_ids`
- `audio_file`
- `audio_sample_count`
- `audio_duration_ms`
- `display_text`
- `spoken_text`
- `subtitle_cue_start_ms`
- `subtitle_cue_end_ms`
- `pause_after_ms`
- `lead_in_ms`
- `tail_hold_ms`
- `cue_checkpoints`
- `flow_insert_intervals`
- `frame_start`
- `frame_end`
- `sample_start`
- `sample_end`

All timestamps must use milliseconds relative to the beginning of the final video.

#### Audio measurement

Generate local lossless audio chunks where supported, preferably WAV PCM.

Use `ffprobe` to record:

- Sample rate.
- Channel layout.
- Sample count where available.
- Measured duration.
- Resampling information.

Prefer exact sample counts over rounded duration strings.

Recalculate sample boundaries after resampling to the common production sample rate.

Do not claim word-level or phoneme-level synchronization. The initial design provides deterministic speech-unit/caption-cue synchronization without Whisper.

If narration, cover duration, pauses, or TTS output changes, invalidate all dependent audio, subtitle, timing, and visual outputs.

### 3.5 Global frame quantization

Target frame rate: 30 FPS.

For a global timestamp (t) in milliseconds and frame rate (f):

[
F(t)=\operatorname{round}\left(\frac{tf}{1000}\right)
]

For a segment from (t_s) to (t_e):

[
N_{\text{frames}}=F(t_e)-F(t_s)
]

Calculate segment frame count using the difference between global frame boundaries. Do not independently round each segment duration.

For audio sample rate (r):

[
S(t)=\operatorname{round}\left(\frac{tr}{1000}\right)
]

Calculate audio sample intervals from global boundaries as well.

Record target timestamps, frame indices, actual frame-aligned times, sample indices, and quantization differences.

The final video duration is frame-quantized. Audio, subtitles, and visual segments must follow the same final duration policy.

### 3.6 Manim camera-aware safe-zone architecture

All camera-moving scientific templates must use `MovingCameraScene` or a project base class derived from it.

The common scene base may inherit `MovingCameraScene` to make `self.camera.frame` available consistently.

Do not use a plain `Scene` while assuming that it exposes `self.camera.frame`.

#### Safe-zone coordinate system

The Safe-Zone Layout System must work in **current camera viewport/screen coordinates**, not only static world coordinates.

At every relevant render frame, it must account for:

- Current camera frame center.
- Current camera frame width and height.
- Current camera zoom.
- Current camera translation.
- Current mobject world-space bounding box.
- The corresponding projected screen-space bounding box.

A camera zoom does not physically expand the world-space bounding box of a mobject. It increases its apparent size in the current viewport and may move projected edges beyond the safe region.

The checker must therefore project objects against the current camera viewport rather than relying on their original world-space bounds.

#### Safe-zone bands

Initial vertical layout, measured from the top of the final frame:

| Range | Purpose | Restrictions |
|---|---|---|
| 0%–10% | Top interface reserve | No essential content |
| 10%–68% | Core scientific animation | Important scientific objects, formulas, labels, and axes |
| 68%–78% | Dedicated subtitle area | No essential Manim content |
| 78%–100% | Bottom WeChat UI reserve | No essential scientific information or subtitles |

Initial horizontal profile:

- Reserve approximately 15% on the right for interaction controls.
- Reserve configurable left margin.
- Keep important content inside the configured rectangle.

These percentages are initial engineering defaults, not permanent WeChat interface guarantees. They must be configurable and calibrated using actual mobile playback previews.

#### Camera-aware validation

The system must validate important objects:

- Before a camera movement.
- At camera movement keyframes.
- During the camera movement at the actual rendered frame rate, or using a demonstrably conservative equivalent.
- After camera movement.
- During other animation actions that change important object positions or dimensions.

A scene may not pass QA merely because it fits the viewport at its initial and final states.

If an object enters a reserved region during an intermediate zoom or pan frame, the layout fails.

#### Camera-anchored overlays

Titles, legends, fixed formulas, and other viewport-anchored UI elements must remain in the intended screen-space location while the camera moves.

Do not blindly call `add_fixed_in_frame_mobjects` on `MovingCameraScene`; that method belongs to the `ThreeDScene` API in the documented Manim interface.

Implement one verified approach:

1. A project-owned `ViewportOverlayManager` that recalculates the overlay's world position and scale from the current camera frame on every relevant frame; or
2. A separate overlay-rendering pass composited after the scientific scene, when that is more reliable for the selected renderer.

The selected approach must be tested with the actual Manim version and renderer.

#### Layout corrections

The safe-zone system must:

- Detect horizontal and vertical overflow.
- Attempt approved reflow, wrapping, repositioning, and controlled scaling.
- Enforce minimum readable font size.
- Reject unrecoverable overflow.
- Record every automatic repair in the QA report.

Do not silently shrink long formulas until they become unreadable.

### 3.7 Manim frame-budget and tail-padding strategy

Manim's animation loop uses floating-point durations and frame-time progression. Multiple independent `play()` and `wait()` calls can produce frame-count differences from the global integer frame budget.

Do not assume that summing floating-point `run_time` values guarantees an exact output frame count.

Implement a deterministic `FrameBudget`/`SceneTimelineDriver`.

Requirements:

1. Convert global cue checkpoints to integer frame indices before rendering.
2. Use integer frame counts for scene actions.
3. Prefer one continuous timeline-driven animation per scene when practical, rather than many independent uncoordinated `play()` calls.
4. If multiple Manim animation blocks are unavoidable, use frame-derived durations and validate their combined output.
5. Ensure every required visual action is complete before the final hold interval.
6. Reserve a configurable final content hold, initially five frames.
7. Render an additional guard tail, initially five frames, beyond the target output duration.
8. Verify the rendered source contains at least the target frame count.
9. Use FFmpeg `trim=end_frame=N_frames` to remove excess frames and reset timestamps.
10. Re-probe the trimmed output to verify the exact frame count and duration.

The final visual state must already have been reached and held before the target output ends. The additional render guard is not a substitute for unfinished animation.

The normalized scene output must contain exactly the required target number of frames after trimming.

**Failure rule:** If Manim produces fewer than the required target frame count, fail the scene and report the discrepancy. Do not hide the failure by silently duplicating frames or stretching timestamps.

A default five-frame guard is acceptable only after tests show that it covers the actual error envelope for the implemented templates and maximum cue count. If tests show a larger error, revise the guard based on measured worst-case behavior.

The QA report must record:

- Target frames.
- Actual rendered frames.
- Guard frames.
- Final trimmed frames.
- Maximum timing discrepancy.
- Whether any action was truncated or incomplete.

### 3.8 Local Chinese TTS and scientific text normalization

Use one local/offline Chinese TTS engine after Windows testing.

Primary candidate:

- `sherpa-onnx` with a compatible Chinese-English MeloTTS-derived ONNX model.

Alternative:

- A supported Windows-compatible MeloTTS deployment.

Select based on actual pronunciation, CPU usage, runtime reliability, and scientific terminology tests.

Do not use online `edge-tts` as the default or silently fall back to online TTS.

Maintain separate:

- `raw_text`
- `display_text`
- `spoken_text`

Use a dedicated scientific pronunciation dictionary.

Test:

- Mandarin.
- English technical terms.
- Chemical formulas.
- Greek letters.
- Mathematical expressions.
- Crystallographic notation.
- Abbreviations.
- Mixed Chinese-English phrases.

Examples:

- `ΔG*` → a reviewed spoken form such as “德尔塔 G 星”.
- `Ostwald` → configured pronunciation.
- `FCC` → configured spoken form.

Unknown or ambiguous expressions must be flagged for review.

### 3.9 Audio pauses and loudness

Assemble one continuous narration track from the TTS chunks and explicit silence segments.

Use:

- Explicit silence audio segments or deterministic timeline operations for sentence pauses.
- `adelay` only for delaying a stream on the timeline.
- `apad` only for trailing audio padding.

Do not use `apad` as a replacement for arbitrary sentence-pause insertion.

Convert all TTS chunks to a consistent sample rate, channel layout, and intermediate format before assembly.

Normalize the assembled narration track as a whole, not every short chunk independently.

Initial configurable targets:

- Integrated loudness: `I = -16 LUFS`.
- Maximum true peak: `TP = -1.5 dBTP`.
- Loudness range target: `LRA = 11`.

Prefer a measured two-pass FFmpeg `loudnorm` workflow where practical.

Measure again after normalization and after final AAC encoding.

Validate on headphones and ordinary mobile speakers.

Record final measured loudness and true peak in the QA report.

### 3.10 FFmpeg normalization and concatenation

All Manim and Flow video segments must be normalized before final concatenation.

Common output profile:

- 1080 × 1920.
- 30 FPS.
- Constant frame rate.
- `yuv420p`.
- `setsar=1`.
- Compatible codec/profile/time base for the selected concatenation method.
- No source audio tracks (`-an`).
- Exact frame count derived from global timeline boundaries.

Do not concatenate heterogeneous Flow and Manim inputs without normalization.

Use either:

- A validated concat filter over normalized inputs; or
- Concat demuxer only when all inputs have matching stream structure, codec, time base, and compatible metadata.

Use the same global frame-boundary calculations when normalizing all segments.

Preserve aspect ratio. Never stretch scientific content to fill the screen.

Burn subtitles only after the final visual concatenation, so cue timestamps remain relative to the final video origin.

### 3.11 Windows subtitle path and font handling

The chosen FFmpeg build must include the `subtitles` filter and libass support.

Generate:

- `captions.srt` for portable cue timing.
- `captions.ass` for precise styling and placement.

Prefer ASS for final burn-in when subtitle positioning and typography need explicit control.

#### Windows path rules

Do not build a subtitle filter by blindly inserting an absolute path such as:

`C:\project\captions.srt`

Prefer:

1. Set the FFmpeg working directory to the task output directory.
2. Refer to the subtitle file using a simple relative filename such as `captions.ass`.
3. Invoke FFmpeg through Python `subprocess` argument lists.
4. Avoid shell command-string construction.
5. Use a dedicated escaping helper only when absolute paths are necessary.
6. Test paths containing spaces, Chinese characters, apostrophes, and other non-ASCII characters.

Do not assume ordinary Windows quoting is equivalent to FFmpeg filtergraph escaping.

#### Font rules

Detect and verify a locally installed Chinese-capable font.

Microsoft YaHei and SimHei are candidates, not guaranteed dependencies.

Verify glyph coverage for Chinese, Greek letters, mathematical symbols, and required punctuation.

If no suitable font exists, stop and report the missing requirement. Do not silently render tofu boxes or unsuitable fallback characters.

Do not redistribute font files without checking licensing.

### 3.12 Flow asset selection and duration handling

Google Flow is optional.

Do not automate its website during daily production.

Use existing credits manually to prepare a local cache:

`assets/flow_cache/`

Each asset must record:

- Asset ID.
- File path.
- Theme tags.
- Description.
- Measured duration.
- Frame rate.
- Resolution.
- Aspect ratio.
- Approval status.
- Provenance.
- `loopable` boolean.
- `loop_mode`.
- `loop_validation_status`.

#### Asset selection

If a Flow asset is intended to fill a complete target interval:

- Prefer assets whose usable duration is at least the interval duration.
- Trim longer assets to the required interval.
- Reject insufficiently long assets for full-interval use unless a valid alternative has been approved.

If a Flow asset is intended only as a short cutaway:

- Use its actual usable duration.
- Assign it a shorter global timeline interval.
- Resume the Manim scene or another approved visual after the cutaway.
- Do not require it to cover the entire voice scene.

#### Short asset fallback order

1. Select another suitable longer asset.
2. Reduce the Flow insert duration and return to Manim or another approved visual.
3. Use a neutral Manim background or another approved local asset.
4. Use looping only when the asset has been explicitly marked `loopable` and its loop quality has been validated.
5. Use ping-pong/reverse playback only for decorative footage where reversing motion cannot imply a false scientific process.

Do not ping-pong crystal growth, diffusion, nucleation, particle attachment, or other directionally meaningful scientific footage.

Do not use `setpts` to slow a short asset artificially.

When looping is approved, normalize to constant frame rate first and use frame-based looping. Inspect the loop boundary and the final visual result.

Flow must never define scientific molecular trajectories, lattice geometry, critical nucleus structure, quantitative curves, or physical mechanisms.

The pipeline must work with Flow disabled.

### 3.13 Manim scene templates and one-minute content density

Initial reusable scene families:

1. Critical nucleus and free-energy barrier.
2. Particle assembly and crystal lattice.
3. Heterogeneous nucleation and interface.
4. Crystal growth front and growth steps.
5. Dendritic growth and morphology evolution.

A typical video must use only the scene families needed to explain its selected scientific question.

Default narrative structure:

- One opening cover segment.
- Two or three main scientific scenes.
- Optional short conclusion/source display.

Approximate narration guideline: 180–220 Chinese characters for a one-minute video. This is a heuristic, not a rigid rule.

Preferred duration: approximately 55–65 seconds.

Actual TTS duration and scientific clarity take priority.

The storyboard schema must enforce:

- One main scientific question.
- One explanatory chain.
- Two or three core scenes by default.
- One primary concept per scene.
- Explicit cue checkpoints.
- No unrelated scientific digressions.
- No unnecessary formulas or terminology.

If the script is too long, narrow the scientific question or simplify redundant explanation. Do not accelerate speech unnaturally.

If the topic cannot be explained accurately in approximately one minute, split it into multiple topics.

All Manim templates must support portrait layout, safe-zone validation, cue checkpoints, claim mapping, integer frame budgets, deterministic rendering, and automated QA.

The LLM selects registered templates and validated parameters. It must not generate unrestricted executable Manim code.

### 3.14 OpenCode Go isolation and structured output

Use OpenCode Go for:

- Narration generation.
- Metadata and storyboard generation.
- Claim-to-script consistency review.
- Limited correction when a validator identifies a specific issue.

Default maximum: three model calls per video.

Every call must use a fresh scratch working directory, not the production project root.

The scratch environment contains only the minimum required Fact Card, prompt, schema, and task output.

Before invoking OpenCode:

1. Detect installed CLI version.
2. Inspect the actual configuration schema and `opencode run --help`.
3. Generate compatible version-specific permissions.
4. Explicitly deny project editing, file writing, shell, web, MCP, unrelated skills/plugins, and subagent/worker spawning.
5. Check inherited global configuration and saved permissions.
6. Verify effective permissions.
7. Fail closed if tool restrictions cannot be demonstrated.

Do not blindly copy V1 permissions into V2.

Do not use `--auto` or blanket permission approval.

Where supported, use:

`opencode run --format json`

Treat output as a newline-delimited JSON event stream.

The parser must:

1. Read stdout line by line.
2. Parse individual JSON events.
3. Record required diagnostic events.
4. Extract the final assistant text from the correct text-bearing content blocks.
5. Reject unexpected tool-call events.
6. Reassemble final text in order.
7. Prefer strict raw JSON.
8. Strip Markdown fences only when a single outer fence wraps the complete response.
9. Avoid broad regular-expression stripping.
10. Parse and validate the result with strict Pydantic or equivalent schemas.
11. Reject unknown scene types, unknown claim IDs, unsupported parameters, and additional scientific claims.
12. Persist only validated output through the Python orchestrator.

Keep version-specific parser fixtures.

One bounded formatting correction is permitted within the three-call budget. If validation still fails, stop.

No hidden workers or recursive delegation.

### 3.15 Cross-day Edge session reuse

**The dedicated Edge browser must be a persistent session that survives the daily Python/BAT process, and that can be safely reused on Day 2 and later runs.**

The same dedicated browser profile must not be launched as a second independent Edge instance while already in use.

Persist session metadata in:

`runtime/edge_session.json`

Required fields:

- `schema_version`
- `edge_executable`
- `edge_pid`
- `process_creation_time`
- `user_data_dir`
- `user_data_dir_fingerprint`
- `remote_debugging_port`
- `edge_version`
- `session_started_at`
- `last_verified_at`

Do not store cookies, authentication tokens, or session secrets in this file.

#### Startup decision order

Before every upload:

1. Read `edge_session.json`.
2. Verify the dedicated profile path and profile fingerprint.
3. Check whether the recorded CDP port responds to `/json/version`.
4. Identify the operating-system process owning the debugging port.
5. Verify that its executable, PID, creation time, command line, user-data directory, and remote debugging port match the recorded dedicated Edge session.
6. If all checks pass, connect Playwright to the existing browser session.
7. Preserve existing review tabs and create a new tab for the next daily job.
8. Do not launch another Edge process with the same user-data directory.

The recorded PID alone is insufficient because Windows PIDs may be reused.

A live TCP port alone is insufficient because it could belong to an unrelated process.

The profile directory alone is insufficient because another Edge process may hold it without a reachable CDP endpoint.

#### Recovery behavior

If the recorded CDP port is unavailable:

- Inspect running Edge processes for the dedicated profile path.
- If an Edge process still owns the profile but no valid CDP endpoint exists, do not launch another instance.
- Report the session recovery issue and ask the user to close/restart the dedicated Edge session safely.
- Do not kill a browser window that may contain the user's review work.

Only when there is no Edge process using the dedicated profile may the system launch a fresh Edge process with that profile.

After a successful fresh launch:

- Verify the CDP endpoint.
- Verify the process command line.
- Verify the expected profile path.
- Verify browser version.
- Write `edge_session.json` atomically.

#### Day 2 behavior

When the previous day's Edge process remains open:

- Reuse its existing CDP port.
- Connect to that process.
- Preserve existing tabs.
- Open a new tab for today's job.
- Upload and verify today's draft.
- Leave the user at the new draft/review page.
- Do not replace or close the previous review tab automatically.

The user may manually close Edge at any time. If it has been closed, the next daily run may start a new dedicated Edge process after confirming the profile is no longer occupied.

### 3.16 Detached Edge process and Playwright lifecycle

Preferred architecture:

1. Start Edge as an independent process using `subprocess.Popen`.
2. Use a dedicated non-default `--user-data-dir`.
3. Enable remote debugging on a loopback-only address.
4. Use a collision-checked local debugging port.
5. Keep Edge outside the renderer/TTS process cleanup group.
6. Connect Playwright using `chromium.connect_over_cdp`.
7. Use the existing persistent default context.
8. Perform upload and draft verification.
9. Navigate to the review page.
10. Persist the verified Edge session metadata.
11. Disconnect the Playwright client using the documented behavior of the installed version.
12. Exit Python without terminating Edge.

Do not assume that a method named `browser.disconnect()` exists in the installed Python API.

Do not call `context.close()` on the persistent context that must survive.

Do not call `edge_process.terminate()` after successful verification.

The exact connection and disconnect behavior must be validated against the installed Playwright and Edge versions.

#### CDP security

- Bind CDP only to loopback.
- Never expose the endpoint to the LAN or public network.
- Use a dedicated profile.
- Do not attach to an ordinary personal Edge profile.
- Do not publish CDP URLs in public logs.
- Verify the process and profile before connecting.
- Protect the dedicated profile against simultaneous uploaders.

### 3.17 Windows kernel-level single-instance mutex

Do not use existence of a `run.lock` file as the truth source for single-instance ownership.

Implement a named Windows mutex through `CreateMutexW` and `WaitForSingleObject`, or a demonstrated equivalent kernel-level lock.

Preferred design:

- Mutex name: a stable identifier derived from the canonical project root and current Windows user identity.
- Namespace: `Local\\...` unless a demonstrated cross-session requirement exists.
- One Python main thread owns and releases the mutex.
- Use a finite acquisition timeout.
- Keep the mutex handle alive for the full production run.

Handle return states explicitly:

- `WAIT_OBJECT_0`: lock acquired normally.
- `WAIT_ABANDONED`: lock acquired after the previous owner terminated unexpectedly; run mandatory recovery audit.
- `WAIT_TIMEOUT`: another instance is active; exit without starting a second job.
- `WAIT_FAILED`: report the Windows error and stop.

Release the mutex in a `finally` cleanup path.

The owner thread must release the mutex. Do not transfer mutex ownership to another thread.

Windows releases the mutex when the owning thread terminates and the handle is closed.

#### Abandoned-mutex recovery

An abandoned mutex means the previous run may have left persistent state inconsistent.

When `WAIT_ABANDONED` occurs:

1. Acquire the mutex ownership.
2. Inspect the task database.
3. Inspect temporary job directories.
4. Verify all completed media assets.
5. Check unfinished TTS/Manim/FFmpeg processes.
6. Inspect browser session metadata.
7. Reconcile any `UPLOAD_UNKNOWN` state.
8. Resume only from a demonstrably safe checkpoint.

Do not assume that acquiring an abandoned mutex automatically makes the previous task state valid.

Do not require the user to delete a residual lock file manually. Diagnostic metadata may remain on disk but does not represent active lock ownership.

#### Child-process lifecycle

Transient Manim, TTS, and FFmpeg subprocesses must be tracked and terminated safely on workflow failure or parent shutdown where possible.

The persistent Edge process must be excluded from the transient render-process cleanup group.

Do not implement a blanket process-tree kill that could terminate the Edge review window.

### 3.18 WeChat Channels draft upload

Use a dedicated persistent Edge profile.

Do not modify the existing public-account browser profile.

Playwright is the preferred automation framework, subject to actual interface testing.

Locator priority:

1. Accessible role and name.
2. Associated labels.
3. Visible text.
4. Placeholder/title attributes.
5. Stable HTML input types.
6. Verified fallback selectors.

Avoid relying solely on dynamic CSS classes, fragile positional XPath, or long DOM ancestry paths.

Keep page selectors in:

`config/selectors.yaml`

#### Before upload

Verify:

- Intended 「成核生长」 account.
- Valid login state.
- Correct video file.
- Upload completion.
- Preview readiness.
- Required metadata.
- No visible validation errors.
- Draft-save control visible and enabled.

#### Save and verify

1. Click the verified draft-save control exactly once per job.
2. Observe the result.
3. Inspect the draft list.
4. Compare with the pre-upload snapshot.
5. Identify the new draft using title, creation time, cover/preview, duration, and platform ID where available.
6. Confirm unpublished status.
7. Navigate to the final review page.
8. Persist verification evidence.
9. Disconnect Playwright while keeping Edge open.

Initial verification polling:

- Approximately every two seconds.
- Maximum five attempts.
- Configurable interval and retry count.

Do not click save again because a toast is missing or the list refresh is delayed.

An uncertain result enters `UPLOAD_UNKNOWN`.

#### Final publication boundary

The automation may upload and save an unpublished draft only.

It must never:

- Click Publish.
- Click Send.
- Click the final confirmation.
- Schedule publication.
- Bypass manual approval.
- Delete or overwrite unrelated drafts.

The user's manual action is the only way to publish the video.

### 3.19 Minimal Windows BAT launcher

The BAT must be a minimal launcher, not a second workflow engine.

Required pattern:

- `@echo off`
- `setlocal`
- `chcp 65001 >nul`
- Python UTF-8 environment settings.
- Project root derived from `%~dp0`.
- Double-quoted paths.
- Project-specific interpreter check.
- Python CLI invocation.
- Proper exit-code propagation.

Example:

```bat
@echo off
setlocal
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=%PROJECT_ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Project Python environment is missing.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -X utf8 -m src.cli run-daily

set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
```

This is an implementation pattern, not a final fixed project path.

Do not put locking, recovery, database operations, rendering, browser logic, or state-machine decisions in BAT.

Python owns all production behavior.

### 3.20 One-minute content capacity

Typical video:

- One opening cover.
- Two or three core scientific scenes.
- Optional short conclusion/source display.
- Approximately 180–220 Chinese characters of spoken content as an initial heuristic.
- Preferred total duration: approximately 55–65 seconds.

The five scene families are a reusable library, not a requirement to use all five in one video.

The storyboard must explain one scientific question and one coherent mechanism.

Use measured TTS duration as the authority.

If the explanation is too long:

- Simplify redundant wording.
- Reduce unnecessary background information.
- Preserve the key scientific claims and applicable conditions.
- Re-generate affected speech units and timeline.
- Never force unnatural speech speed.

If the subject cannot be responsibly explained in about one minute, narrow it or divide it into multiple videos.

---

## 4. Scope

### In scope

- Independent science-animation project.
- One primary daily BAT.
- Optional Fact Card preparation BAT.
- Isolated Python runtime.
- Verified Topic Pool.
- Crossref/OpenAlex metadata discovery and caching.
- Local PDF/BibTeX search.
- Human-approved scientific Fact Cards.
- Claim-to-script and claim-to-animation mapping.
- OpenCode Go structured generation.
- Scratch directory and version-aware permissions.
- Speech-unit segmentation and local Chinese TTS.
- Canonical audiovisual timeline.
- Scene cue checkpoints.
- Global frame/sample quantization.
- Portrait Manim camera-aware safe zones.
- Integer frame-budget and tail-padding strategy.
- Five reusable Manim scene families.
- Two-to-three-scene content-density constraint.
- FFmpeg video normalization and concatenation.
- Windows-safe subtitle rendering.
- Voice pause assembly and full-track loudness normalization.
- Optional cached Flow inserts.
- Edge cross-day CDP session reuse.
- Windows kernel mutex.
- Playwright draft uploader.
- `UPLOAD_UNKNOWN` reconciliation.
- Persistent task state and safe recovery.
- Technical and scientific QA.
- Three-milestone, two-slice development process.

### Out of scope

- Modifying `Tuzhidingdong/WeChat_control`.
- Automatic publication or scheduling.
- Automatic approval of Fact Cards.
- Reusing public-account articles as the default video source.
- Paid API, paid TTS, newly purchased Flow credits, or new subscriptions.
- OpenCode Go extra usage or paid fallback.
- Daily automated Flow website operation.
- New GPU hardware.
- Large multi-agent architecture.
- Unrestricted LLM-generated Manim code.
- Unverified custom-cover crop-modal automation.
- Publishing to other platforms.
- Multiple Channels accounts in the initial version.
- Automatic deletion or overwriting of existing drafts.
- Running the production BAT on the user's behalf as final acceptance.

---

## 5. Architecture / constraints

- **Runtime(s):**
  - Windows 10/11.
  - BAT as the user-facing launcher.
  - Python for orchestration, validation, and state management.
  - PowerShell for focused Windows diagnostics and process operations when necessary.
  - Manim Community Edition.
  - FFmpeg and `ffprobe`.
  - One selected offline Chinese TTS engine.
  - Microsoft Edge.
  - Playwright Python with CDP connection.
  - SQLite or equivalent persistent job state.
  - JSON/JSONL structured artifacts.

- **Isolation:**
  - Independent project directory.
  - Project-specific Python environment.
  - Pinned dependency versions.
  - Dedicated Edge user-data directory.
  - Isolated OpenCode scratch directories.
  - Dedicated runtime metadata.
  - No modification of the existing public-account project or browser profile.

- **Cost constraints:**
  - Zero additional budget.
  - Existing OpenCode Go and Google AI Pro subscriptions only.
  - Maximum three LLM calls per video by default.
  - No hidden worker spawning.
  - No paid APIs or online TTS fallback.
  - No daily Flow website automation.
  - No new hardware purchase.
  - Cache free academic metadata queries and respect public access limits.

- **Security and permission constraints:**
  - No secrets in committed files.
  - OpenCode receives only the minimum required inputs.
  - Fail closed if effective permissions cannot be verified.
  - CDP binds only to loopback.
  - Dedicated Edge profile only.
  - Verify Edge process identity before reuse.
  - Do not kill the dedicated Edge process after successful upload.
  - Do not terminate the user's normal Edge processes.
  - No automatic account switching.
  - No final publish/send action.
  - No blind upload retries.

- **Runtime constraints:**
  - One named kernel mutex per project and user.
  - Explicit handling of abandoned mutex state.
  - Persistent Edge session metadata.
  - Cross-day CDP reuse.
  - Do not start a second Edge process against an occupied profile.
  - Use a separate lifecycle for persistent Edge and transient rendering subprocesses.
  - All external subprocesses have bounded timeouts.

- **Other non-negotiable rules:**
  - Daily production consumes only approved Fact Cards.
  - Bibliographic metadata alone is not scientific evidence.
  - Narration audio precedes final animation rendering.
  - Cover, voice, subtitles, animation, and Flow use one global timeline.
  - Scene-internal visual events use cue checkpoints.
  - Safe-zone validation uses the current camera viewport.
  - Camera-anchored overlays must remain in screen space.
  - Manim's internal frame count must be verified, not assumed.
  - Excess frames may be trimmed; insufficient frames must fail.
  - Flow assets must not be slowed or semantically reversed to fill time.
  - The three milestones must be completed in order.
  - The user performs all final acceptance and publication.

---

## 6. Acceptance criteria

### Milestone 1 — Slice A: Minimum complete local video path

**Goal:** Prove one complete, real local production path before building the full template library or browser uploader.

Use one human-approved Fact Card about critical nuclei/free-energy barriers.

Implement only the minimum components needed for the first complete video:

- Environment preflight.
- One local Chinese TTS candidate, with `sherpa-onnx` as the initial candidate.
- Speech-unit segmentation.
- One audio file per speech unit.
- `audio_timing.json`.
- One-second explicit cover segment.
- One Manim template: critical nucleus/free-energy barrier.
- Scene cue checkpoints.
- One portrait safe-zone profile.
- Subtitle generation and FFmpeg hard-subtitle rendering.
- Final FFmpeg MP4 assembly.

The first sample may use one Manim template family more than once. It must not be forced to use all five template families.

Slice A does not need:
- Complete topic-pool management.
- WeChat uploader.
- Flow integration.
- Five-template library.
- Advanced theme variations.
- Complex production state machines.

It must have enough logging and artifact persistence to reproduce and debug the golden path.

**Slice A acceptance criteria**

- [ ] AC-01: A project-specific Python environment is established without modifying global Python.
- [ ] AC-02: Manim, FFmpeg, and `ffprobe` pass environment preflight.
- [ ] AC-03: The selected LaTeX distribution completes a smoke-test render without interactive package prompts.
- [ ] AC-04: The daily render path never attempts interactive dependency installation.
- [ ] AC-05: External processes have bounded timeouts and useful diagnostics.
- [ ] AC-06: The selected local Chinese TTS engine runs offline on Windows.
- [ ] AC-07: Representative Mandarin and scientific terms pass an actual listening test.
- [ ] AC-08: Raw, displayed, and spoken text are stored separately.
- [ ] AC-09: Every speech unit has one audio file and one matching subtitle cue.
- [ ] AC-10: `ffprobe` records the real audio duration and sample metadata.
- [ ] AC-11: `audio_timing.json` contains the explicit opening cover at 0–1000 ms.
- [ ] AC-12: The first narration cue begins at or after the cover ends.
- [ ] AC-13: Subtitle timestamps use the final MP4 global time origin.
- [ ] AC-14: The critical-nucleus template receives scene-relative cue checkpoints.
- [ ] AC-15: Important Manim events occur at their designated cue checkpoints.
- [ ] AC-16: The scene renders in portrait 9:16 composition.
- [ ] AC-17: The subtitle area is reserved and does not overlap essential Manim objects.
- [ ] AC-18: The video segment is normalized to 1080×1920, 30 FPS, `yuv420p`, and `setsar=1`.
- [ ] AC-19: The subtitle filter works with the actual selected Chinese font.
- [ ] AC-20: The subtitle path works with spaces and Chinese characters in Windows paths.
- [ ] AC-21: The final MP4 is approximately 55–65 seconds.
- [ ] AC-22: The video passes media-probe, subtitle, audio, and duration checks.
- [ ] AC-23: No Flow footage is required for Slice A.
- [ ] AC-24: The first sample includes a Fact Card, source record, script, storyboard, audio files, timing JSON, subtitles, MP4, and a concise QA report.
- [ ] AC-25: The user can play the complete video and judge scientific pronunciation, layout, subtitle timing, and audiovisual synchronization.

**Slice A exit condition:** One complete, locally generated portrait MP4 is inspected and accepted by the user. Do not begin full-template development until the actual Windows rendering and TTS issues have been exposed and addressed.

### Milestone 1 — Slice B: Complete templates and three sample videos

**Template and camera architecture**

- [ ] AC-26: The remaining four scientific scene families are implemented.
- [ ] AC-27: The five scene families are reusable and parameterized.
- [ ] AC-28: Daily videos use two or three main scientific scenes by default.
- [ ] AC-29: Camera-moving templates use `MovingCameraScene` or an equivalent verified project base.
- [ ] AC-30: Safe-zone validation uses current camera viewport geometry.
- [ ] AC-31: Important objects are checked during camera movement, not only at the beginning and end.
- [ ] AC-32: Camera zoom and pan cannot silently push important objects outside the safe rectangle.
- [ ] AC-33: Viewport-anchored labels and titles remain fixed relative to the screen.
- [ ] AC-34: The overlay implementation does not call unsupported ThreeDScene-only methods on MovingCameraScene.
- [ ] AC-35: All important formulas, labels, and axes pass projected-screen-space checks.
- [ ] AC-36: Unrecoverable overflow or unreadable scaling blocks rendering.

**Manim frame budget**

- [ ] AC-37: Cue timing is converted to integer global frame indices.
- [ ] AC-38: The renderer uses a consistent per-scene frame budget.
- [ ] AC-39: The template avoids unnecessary independently rounded `play()`/`wait()` blocks where a continuous timeline driver is practical.
- [ ] AC-40: The final content state is reached before the reserved terminal hold.
- [ ] AC-41: The renderer adds a configurable terminal hold and a measured render guard.
- [ ] AC-42: The initial render guard is five frames and is validated against the actual maximum error envelope.
- [ ] AC-43: FFmpeg trims excess frames using the target `end_frame` count and resets timestamps.
- [ ] AC-44: A rendered file shorter than the target frame count fails instead of being silently padded or stretched.
- [ ] AC-45: The final trimmed frame count exactly matches the global frame budget.

**Visual and audio QA**

- [ ] AC-46: The assembled voice track receives full-track loudness normalization.
- [ ] AC-47: Final loudness and true peak are measured.
- [ ] AC-48: All subtitle cues use the same global timing data as Manim.
- [ ] AC-49: Flow assets are normalized before integration.
- [ ] AC-50: Flow assets shorter than a full target interval are handled using the approved fallback order.
- [ ] AC-51: Short Flow clips are not slowed with `setpts`.
- [ ] AC-52: Ping-pong is prohibited for scientific processes whose direction is meaningful.
- [ ] AC-53: Flow can be disabled without blocking production.
- [ ] AC-54: All visual content remains readable on a mobile screen.
- [ ] AC-55: The system creates three representative sample videos covering nucleation, crystal growth, and ice/crystal morphology.
- [ ] AC-56: The three sample videos have complete scientific and technical review packages.
- [ ] AC-57: The user has inspected and accepted all three videos on a mobile screen.

**Slice B exit condition:** Three complete portrait MP4s have passed technical QA and user review. Only then is Milestone 1 complete.

### Milestone 2 — Independent WeChat Channels draft-upload proof

**Cross-day Edge session management**

- [ ] AC-58: The uploader uses a dedicated non-default Edge user-data directory.
- [ ] AC-59: Edge is launched as an independent process with a CDP endpoint bound to loopback.
- [ ] AC-60: The session registry records PID, process creation time, executable, profile path/fingerprint, port, and Edge version.
- [ ] AC-61: The system verifies the process owning the CDP port.
- [ ] AC-62: The stored PID is validated using process creation time to avoid PID-reuse errors.
- [ ] AC-63: A valid existing CDP session is reused rather than launching another Edge instance.
- [ ] AC-64: A new daily run opens a new tab and preserves existing review tabs.
- [ ] AC-65: The workflow does not launch a second Edge process while the dedicated profile is already in use.
- [ ] AC-66: If the profile is occupied but the CDP endpoint is unavailable, the system fails safely and requests manual recovery.
- [ ] AC-67: If no process uses the profile, a new Edge process may be launched.
- [ ] AC-68: The Edge process remains alive after Python and BAT exit.
- [ ] AC-69: Playwright's documented disconnect behavior is tested against the installed version.
- [ ] AC-70: No unsupported `browser.disconnect()` method is assumed.
- [ ] AC-71: The persistent context and Edge process are not closed by the upload workflow.
- [ ] AC-72: The CDP endpoint is never exposed to the LAN or public network.

**Upload and draft verification**

- [ ] AC-73: The uploader verifies the intended 「成核生长」 account.
- [ ] AC-74: Login expiry is detected and reported.
- [ ] AC-75: Manual login is followed by a fresh account-identity check.
- [ ] AC-76: Semantic locators are prioritized over dynamic CSS selectors.
- [ ] AC-77: Upload completion, preview readiness, metadata, and enabled save state are verified.
- [ ] AC-78: Default first-frame cover behavior is tested.
- [ ] AC-79: The draft-save action is clicked no more than once per job.
- [ ] AC-80: The new draft is matched against the pre-upload draft-list snapshot.
- [ ] AC-81: Draft verification uses bounded polling.
- [ ] AC-82: An uncertain result enters `UPLOAD_UNKNOWN`.
- [ ] AC-83: A timeout after draft saving cannot trigger another upload.
- [ ] AC-84: An existing draft for the same job blocks duplicate submission.
- [ ] AC-85: After successful verification, Edge remains open at the review interface.
- [ ] AC-86: No automated path clicks Publish, Send, or final confirmation.
- [ ] AC-87: The user can inspect the unpublished draft after the automation exits.

**Milestone 2 exit condition:** One real-account test draft has been saved and verified by the user, without publication. The Edge review window remains open after Python/BAT exit.

### Milestone 3 — Integrated daily BAT workflow

**Windows BAT and mutex**

- [ ] AC-88: `Run_Daily_Video.bat` starts the workflow by double-clicking.
- [ ] AC-89: BAT sets UTF-8 console and Python output.
- [ ] AC-90: BAT derives project paths from `%~dp0` and quotes every path.
- [ ] AC-91: BAT only checks the project interpreter and forwards to the Python CLI.
- [ ] AC-92: Python owns locking, state recovery, disk checks, rendering, and upload decisions.
- [ ] AC-93: The single-instance lock uses a Windows kernel-level mutex rather than lock-file existence.
- [ ] AC-94: Mutex acquisition uses a finite timeout.
- [ ] AC-95: `WAIT_OBJECT_0`, `WAIT_ABANDONED`, `WAIT_TIMEOUT`, and `WAIT_FAILED` are handled explicitly.
- [ ] AC-96: An abandoned mutex triggers a durable job-state recovery audit.
- [ ] AC-97: The mutex is released in a `finally` path and ownership remains on the correct thread.
- [ ] AC-98: Closing or crashing the Python process releases kernel mutex ownership.
- [ ] AC-99: Transient renderer subprocesses are managed separately from the persistent Edge process.

**OpenCode**

- [ ] AC-100: OpenCode uses a fresh scratch directory for every model task.
- [ ] AC-101: The installed CLI version and effective permissions are verified before use.
- [ ] AC-102: Editing, writing, shell, web, MCP, and worker-spawning tools are denied for text-generation calls.
- [ ] AC-103: OpenCode cannot inspect the entire production project or browser profile.
- [ ] AC-104: The default maximum model-call count is three per video.
- [ ] AC-105: The JSON event-stream parser handles the installed CLI's tested NDJSON structure.
- [ ] AC-106: Markdown fences are removed only when they wrap the complete response.
- [ ] AC-107: Model output passes strict schema validation before use.

**Topic pool, state, and integrated run**

- [ ] AC-108: Daily selection uses only human-approved Fact Cards.
- [ ] AC-109: Previously published, processing, and duplicate topics are excluded.
- [ ] AC-110: An empty Verified Topic Pool produces a safe exit.
- [ ] AC-111: Every job records a unique ID, Fact Card ID, timeline version, model-call count, stage state, and outputs.
- [ ] AC-112: Interrupted jobs resume only from verified safe checkpoints.
- [ ] AC-113: A completed or uncertain upload cannot be automatically submitted again.
- [ ] AC-114: One successful daily run creates at most one unpublished draft.
- [ ] AC-115: The review package contains all scientific, audio, timing, visual, subtitle, and QA artifacts.
- [ ] AC-116: The browser is still open after successful draft verification and BAT exit.
- [ ] AC-117: The existing `WeChat_control` project and browser profile remain unchanged.
- [ ] AC-118: The complete system requires no paid service, online TTS, new Flow credits, or new hardware.

### Fact Card preparation

- [ ] AC-119: `Prepare_Fact_Cards.bat` prepares candidate Fact Cards independently from daily production.
- [ ] AC-120: Local PDF/BibTeX search is available where appropriate.
- [ ] AC-121: Crossref/OpenAlex metadata queries are cached and respect free public access limits.
- [ ] AC-122: Bibliographic DOI/title/author/year consistency is checked.
- [ ] AC-123: Metadata alone cannot mark claims scientifically verified.
- [ ] AC-124: Each scientific claim records its evidence locator and verification status.
- [ ] AC-125: The Markdown review queue highlights directly abstract-supported claims and claims requiring full-text checks.
- [ ] AC-126: Candidate Fact Cards cannot enter the Verified Topic Pool without explicit human approval.

---

## 7. Tests / evidence

### Milestone 1 — Slice A test

Use one approved critical-nucleus Fact Card.

Test:

1. Project environment and Manim dependencies.
2. LaTeX smoke test with no interactive prompts.
3. Local Chinese TTS installation and pronunciation.
4. Speech-unit segmentation.
5. Audio duration measurement.
6. `audio_timing.json`.
7. Explicit 1000 ms cover segment.
8. Cue-level subtitle timestamps.
9. Critical-nucleus Manim template.
10. Cue-checkpoint animation timing.
11. Portrait safe-zone.
12. FFmpeg subtitle burn-in with Chinese text.
13. Final MP4 frame rate, resolution, duration, and audio.
14. Full manual playback and listening.

**Deliverable:** One complete approximately one-minute MP4 and all its review artifacts.

Do not spend Slice A building the full topic database, uploader, all five templates, a complex task framework, or a Flow integration.

### Milestone 1 — Slice B test

1. Implement and test the remaining four scene families.
2. Test moving camera zoom and pan.
3. Verify safe-zone projection at intermediate frames.
4. Test viewport-anchored overlays.
5. Test scenes with multiple cue checkpoints.
6. Compare target and actual Manim frame counts.
7. Verify tail-padding and `trim=end_frame` behavior.
8. Verify exact final frame count.
9. Test FFmpeg inputs at 24 FPS and differing pixel formats.
10. Test relative subtitle paths with spaces and Chinese characters.
11. Verify the selected Chinese font and glyphs.
12. Test full narration loudness normalization.
13. Test a Flow asset longer than its target interval.
14. Test a Flow asset shorter than its intended interval.
15. Verify the fallback order and loopability rules.
16. Render nucleation, crystal growth, and ice/crystal morphology samples.
17. Inspect all samples on a mobile screen.

### Milestone 2 test

1. Launch Edge independently from Python.
2. Verify its PID and dedicated profile path.
3. Verify CDP loopback binding.
4. Connect Playwright.
5. Verify the dedicated profile and intended account.
6. Disconnect Playwright and confirm Edge remains open.
7. Run the next simulated daily job while Edge remains open.
8. Verify the existing browser session is reused.
9. Confirm a new tab is created and old tabs remain intact.
10. Confirm no second Edge process with the same profile is launched.
11. Simulate stale `edge_session.json`.
12. Simulate a dead CDP port while the dedicated profile is still in use.
13. Verify safe manual recovery.
14. Upload one unpublished test video.
15. Verify draft save and list reconciliation.
16. Simulate timeout immediately after save.
17. Verify `UPLOAD_UNKNOWN` prevents duplicates.
18. Confirm no final publish action occurs.

### Milestone 3 test

1. Double-click the daily BAT.
2. Verify UTF-8 output with Chinese paths.
3. Start a second BAT instance and confirm mutex blocking.
4. Simulate abnormal termination while holding the mutex.
5. Verify the next run receives the abandoned state and performs recovery.
6. Confirm no user action to delete a lock file is required.
7. Simulate interrupted Manim/FFmpeg/TTS child processes.
8. Verify transient-process cleanup does not close Edge.
9. Verify Verified Topic Pool selection.
10. Verify OpenCode permissions and call limit.
11. Verify one successful run creates one draft.
12. Verify Day 2 Edge reuse.
13. Verify the final browser stays open after the BAT exits.
14. Verify the complete review package and status report.

### Regression tests

- Existing `WeChat_control` remains unchanged.
- Existing public-account browser profile remains unchanged.
- No unrelated Channels drafts are modified or deleted.
- Flow unavailable does not block local production.
- No online TTS fallback.
- No paid API fallback.
- No unapproved Fact Card enters production.
- Cover does not shift subtitles.
- Scene cue checkpoints remain aligned with narration.
- Camera zoom does not violate safe zones.
- Manim frame mismatch is detected and reconciled.
- FFmpeg does not accumulate per-segment rounding drift.
- Windows subtitle paths remain valid.
- Edge is reused on the next day rather than relaunched against an occupied profile.
- Abnormal exit does not leave a permanent lock.
- Persistent Edge is never killed by transient-render cleanup.
- No automatic publication.
- No blind upload retry.

### Manual acceptance

Antigravity and workers must not run the user's production BAT on the user's behalf as a substitute for real-world acceptance.

**Slice A**

1. Inspect the first complete video.
2. Listen to TTS pronunciation and pacing.
3. Check subtitles, cover, and scientific labels.
4. Confirm that speech units and animation events are synchronized.
5. Approve the golden path.

**Slice B**

1. Inspect all three representative videos on a mobile device.
2. Check each scene family and visual transition.
3. Verify equations, labels, subtitles, and safe zones.
4. Approve Milestone 1.

**Milestone 2**

1. Inspect the unpublished test draft.
2. Confirm title, cover, and video content.
3. Confirm that the draft remains unpublished.
4. Run the Day 2 session-reuse test.
5. Confirm Edge remains open after the automation exits.
6. Approve Milestone 2.

**Milestone 3**

1. Double-click the production BAT.
2. Inspect the final video and review package.
3. Confirm exactly one correct unpublished draft exists.
4. Confirm that Edge remains open.
5. Confirm that the automation has not published the video.
6. Personally click the final publication action only after approval.

---

## 8. Deliverables

1. Independent science-animation project directory/repository.
2. `Run_Daily_Video.bat`.
3. `Prepare_Fact_Cards.bat`.
4. Project-specific Python environment and pinned dependencies.
5. Preflight and environment setup scripts.
6. Verified Topic Pool and topic history.
7. Crossref/OpenAlex discovery and caching module.
8. Local PDF/BibTeX reference search integration.
9. Scientific Fact Card schema and source registry.
10. Claim-to-script and claim-to-animation validator.
11. OpenCode scratch wrapper and version-aware permission configuration.
12. OpenCode NDJSON event parser and tests.
13. Structured storyboard schema.
14. Speech-unit segmentation module.
15. Local Chinese TTS integration.
16. Scientific pronunciation dictionary and normalizer.
17. Canonical `audio_timing.json` schema.
18. Global frame/sample quantization module.
19. Manim `SceneTimelineDriver` and scene cue-checkpoint interface.
20. Manim camera-aware `SafeZoneLayout`.
21. Viewport overlay manager or verified overlay-rendering alternative.
22. Five reusable scientific animation templates.
23. Integer frame-budget and tail-guard implementation.
24. SRT/ASS subtitle generator.
25. Full-track audio pause and loudness-normalization module.
26. FFmpeg segment normalization and concatenation.
27. Windows-safe subtitle path/font validation.
28. Optional Flow asset registry and fallback selector.
29. Windows kernel mutex implementation.
30. Persistent Edge/CDP session registry and reuse manager.
31. Detached Edge launcher and lifecycle tests.
32. WeChat Channels unpublished-draft uploader.
33. `selectors.yaml` and browser diagnostics.
34. Persistent task-state and `UPLOAD_UNKNOWN` reconciliation.
35. Three complete sample videos and review packages.
36. Installation, setup, daily use, troubleshooting, and recovery documentation.
37. `STATUS.md` recording milestone status, evidence, unresolved risks, and release readiness.

---

## 9. Release boundary

- [ ] Code/files only; do not publish.
- [x] Prepare a release candidate; wait for my approval before publishing.
- [x] Other:

**Authorized boundary**

- Antigravity may implement and test the local production system.
- Antigravity may prepare a release candidate.
- Antigravity must not publish or schedule videos.
- Antigravity and workers must not run the production BAT as a substitute for user acceptance.
- The user personally runs the production BAT for real-world acceptance.
- When the user explicitly runs the BAT, it is authorized to upload one video as an unpublished draft to the intended Channels account.
- The workflow must stop after saving and verifying the unpublished draft.
- The final publish/send action is always manual.
- The first real-account upload is a controlled draft-only test.
- The existing public-account automation must remain unchanged.
- Do not claim production readiness until all milestone exit conditions have passed.

---

## 10. User decisions already made

The following decisions are final and must not be asked again:

1. **Project identity:** The account is 「成核生长」 and is independent of the existing public account.
2. **Daily operation:** One double-click of `Run_Daily_Video.bat` starts one complete daily production run.
3. **Final behavior:** Automatically create and verify one unpublished Channels draft. The user personally inspects and publishes.
4. **Format:** Approximately one-minute vertical scientific animation.
5. **Scientific scope:** Nucleation, crystal growth, minerals, inorganic crystals, organic crystals, ice, nucleation/growth theory, phase transitions, and related subjects.
6. **Editorial independence:** Do not simply convert existing public-account articles into videos.
7. **Visual approach:** Manim for scientific animation, with optional cached Flow cutaways or framed inserts.
8. **Flow dependency:** Flow is optional. Use only existing credits. No daily Flow website automation.
9. **Voice:** Free local Chinese TTS. No paid online TTS. Select the engine using Windows and pronunciation tests.
10. **Scientific standard:** Evidence-backed claims, source locators, explicit assumptions, and distinction between observation, theory, and schematic visualization.
11. **Topic pool:** Daily production consumes only human-approved Fact Cards.
12. **Metadata:** Crossref/OpenAlex metadata assists discovery but cannot by itself verify scientific claims.
13. **Audio-first production:** Generate speech-unit audio and measure it before final Manim rendering.
14. **Subtitle synchronization:** Each natural speech unit corresponds to one audio chunk and subtitle cue. Initial synchronization is cue-level, not word-level.
15. **Global timeline:** Cover, voice, subtitles, animation, and Flow all share one global timeline.
16. **Cover:** One-second opening cover is an explicit segment from 0 ms, not a later FFmpeg prepend.
17. **Scene synchronization:** Every Manim scene receives scene-relative cue checkpoints and explicit visual trigger IDs.
18. **Frame handling:** Use global integer frame/sample boundaries. Reserve a validated render guard and trim excess frames. Never conceal insufficient frames.
19. **Camera:** Camera-moving templates use `MovingCameraScene` or a verified equivalent, with live viewport-space safe-zone checks.
20. **Viewport overlays:** Titles and fixed UI elements must remain in screen space using a verified overlay approach.
21. **Audio quality:** Insert explicit pauses and normalize the complete narration track.
22. **FFmpeg:** Normalize input clips before concatenation and handle Windows subtitle paths/fonts explicitly.
23. **OpenCode Go:** Maximum three model calls by default; use scratch isolation, verified version-specific permissions, and strict output parsing. No hidden workers.
24. **Cross-day browser:** Reuse a verified persistent Edge/CDP session and do not start a second instance against an occupied profile.
25. **Browser lifecycle:** Edge must remain open after Python/BAT exits so the user can inspect the draft.
26. **Single-instance protection:** Use a Windows kernel-level mutex, not lock-file existence as the source of truth.
27. **Interrupted runs:** An abandoned mutex triggers recovery validation. Uncertain uploads must be reconciled before any new upload.
28. **Short Flow assets:** Prefer longer assets or shorter cutaways. Loop only when explicitly approved and visually validated. Never slow semantically meaningful motion or reverse a scientific process.
29. **Content density:** Two or three main scientific scenes per typical one-minute video. Five templates are a reusable library, not a per-video checklist.
30. **Duration:** Approximately 55–65 seconds is the preferred initial range. Measured TTS duration and scientific clarity take priority over rigid character counts.
31. **Budget:** Zero additional budget. No paid extra usage, paid fallback, online TTS, Flow purchases, or new hardware.
32. **Project isolation:** The existing `Tuzhidingdong/WeChat_control` files and browser profile remain unchanged.
33. **Development order:** Milestone 1 Slice A, Milestone 1 Slice B, Milestone 2, Milestone 3. Strictly sequential.
34. **Final acceptance:** The user reviews the first Slice A video, then all three Slice B samples, before allowing the draft-upload milestone.
35. **Publication boundary:** Never automatically publish, schedule, or click the final send confirmation.
