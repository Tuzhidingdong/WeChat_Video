# 「精读一分钟」文章摘要视频工作流

**Status:** daily literature pipeline is being integrated on `feat/daily-literature-and-popularization`; video draft upload no longer depends on the WeChat extended-link feature.

## 1. Product boundary

「精读一分钟」 is a separate Chinese-language content type. Its source is an article that has already been published by the 「成核生长」 WeChat Official Account. It is not a shortened version of the critical-nucleus explainer series.

The pipeline consumes a sanitized, local article package exported by the publishing workflow. Its taxonomy mirrors the upstream record: editorial_slot=1, article_type=literature_translation, and editorial_pillar_id=literature_manuscript. It does not access or reuse the WeChat_control browser profile, cookies, access tokens, or private platform APIs. This keeps the Video project isolated from the WeChat_control account session and browser automation.

## 2. Automatic source package contract

The production BAT does **not** ask the user to create or copy an article package. It discovers completed Slot 1 runs from the existing local WeChat_control output at `../data/daily_runs/<date>/research_subscription/<run_id>/`.

The Video adapter reads the existing run's `slot1.md`, `slot1.manifest.json`, `prepared_articles.json`, `review_state.json`, `delivery_result.json`, `uploaded_assets_manifest.json`, and the recorded publication-evidence files. It verifies the full Markdown hash chain and the `literature_translation` / `literature_manuscript` taxonomy before considering the run.

Formal publication time is derived only from the positive Unix-epoch `ct` field in the same run's `article_read_count_probe.json`, with provenance retained in the materialized package. For the inspected sample, `ct=1795308507` corresponds to `2026-11-22T00:48:27Z` (`2026-11-22 08:48:27` Asia/Shanghai). The upstream run's `article.json.published_at` value is a draft/worker timestamp and must never be used as the formal publication time.

The canonical public article URL is read from the recorded official album DOM evidence, specifically `li.album__list-item[data-link]`, and must agree with the read-only URL provenance. The official album page's `data-msgid` (mid) is retained separately from the publishing `delivery_result.json.appmsgid`; the two identifiers are not interchangeable. The adapter does not open a browser, use cookies/tokens, or call private APIs.

After these checks pass, Video creates a non-overwriting package in its own runtime cache:

```
runtime/upstream_article_packages/<appmsgid>_0/<run_id>/
  article.json
  article.md
  images.json
  images/
```

`article.md` is a byte-identical copy of upstream `slot1.md`. Only locally present, decodable original images with caption/context grounded in the article Markdown are copied; unverified CDN-only images are not downloaded or fabricated. The generated `article.json` stores account/taxonomy identity, formal publication time, canonical URL and its provenance, publication-time provenance, album identity and upstream run provenance.

A missing, ambiguous or mismatched source-evidence field rejects that candidate. It does not cause the adapter to substitute the draft timestamp or manufacture a published timestamp. No eligible article produces `SKIPPED_NO_ELIGIBLE_ARTICLE`, with per-run rejection reasons.

The following package schema describes the **internal generated artifact** only; it is not a manual user input requirement:

```json
{
  "schema_version": 1,
  "account_name": "成核生长",
  "editorial_slot": 1,
  "article_type": "literature_translation",
  "editorial_pillar_id": "literature_manuscript",
  "publication_status": "PUBLISHED",
  "appmsgid": "100000764",
  "article_id": "100000764_0",
  "title": "Exact published Slot 1 article title",
  "published_at": "2026-11-22T00:48:27Z",
  "canonical_url": "the observed official published article URL",
  "canonical_url_verified": true
}
```

`images.json` contains only validated local image paths and article-grounded captions/context. The source Markdown is copied without rewriting or newline normalization so the source SHA-256 remains identical to the upstream Slot 1 artifact.

## 3. Summary script contract

The model or editor creates a separate summary.json. Its source hash must match article.md. Every claim must include an exact source excerpt, and each spoken unit and visual beat must map to one or more of those claim IDs.

Content-planning instructions for the reusable authoring prompt:

- For each specialist concept that is important to the story, first formulate a short plain-language explanation, then introduce the exact scientific/professional term. Keep both grounded in the same claim IDs; the plain-language line must not imply a different mechanism or stronger certainty.
- Keep technical terms, quantitative values, units, experimental conditions, comparison direction, uncertainty, limitations and causal wording traceable to the evidence map. Plain-language phrasing is an access layer, not a scientific rewrite.
- Prefer removing repetition and simplifying sentence structure over deleting a result. If the 58–62 second target cannot be reached while retaining material evidence, report the conflict rather than dropping a claim.
- For a figure that contains an embedded article caption or unreadable small-print block, propose a normalized `display_crop_regions` rectangle for that image. Preserve the axes, tick marks, legends, units, significant data marks and any evidence needed to understand the figure. The original asset remains unchanged.
- When a graph is shown without clear Chinese explanation of its variables, provide grounded `axis_labels_zh` entries (`x` and/or `y`) for the relevant image. Never infer a variable meaning from the shape of a curve alone; use the figure's own labels and the linked source claims.

Top-level fields:

- schema_version: 1
- article_id: exact match with article.json
- source_article_sha256: SHA-256 of the exact article.md bytes on disk (read the file in binary mode; do not hash an in-memory string with different newline conversion)
- summary_title: editorial title for the video
- channels_title: explicit 6–16 character Channels short title
- core_thesis: one sentence describing the article's central point
- thesis_claim_ids: one or more claim IDs that support the core thesis
- claims: claim_id, statement, and source_excerpt
- speech_units: 5–8 Chinese narration units
- beats: exactly one visual beat per speech unit

Each speech unit includes unit_id, spoken_text, display_text, claim_ids, and visual_trigger_ids. Each beat includes beat_id, unit_id, kind, headline, and claim_ids.

Supported beat kinds:

- hook: opening question or counter-intuitive finding
- image: one or two actual article images, displayed with contain by default; an evidence-preserving display crop may be declared per image when source-figure whitespace or embedded caption blocks impair mobile readability
- stat: one article-grounded numerical result
- compare: comparison supported by cited claims
- mechanism: two to four explanatory steps
- quote: an exact excerpt from the article
- takeaway: final conclusion and practical meaning

Three consecutive beats may not use the same visual type. Numeric values in stat_value must occur in the article source text. Quoted text must exactly match the article after whitespace normalization.

The source-grounded script remains 5–8 speech units, with every claim retained in the evidence map. For this one-minute editorial format, the calibrated planning target is **222–235 CJK characters**, with the final programme measured at **58–62 seconds**. The planning estimate is checked before TTS; the actual PCM sample-clock duration is checked after synthesis and before scene rendering. A mismatch stops the run and asks for a revised content plan. The engine does not time-stretch audio, silently remove claims, or repeatedly accelerate a completed narration.

## 4. Local commands

The default Slice A English voice and its personal OpenVoice profile are unchanged. The Chinese article-summary workflow now defaults to **Edge-TTS / zh-CN-XiaoxiaoNeural**, selected by the user's A/B blind listening. This is an online Microsoft Edge speech endpoint accessed through the pinned `edge-tts` community client; narration text is sent to that service.

Install the optional provider once into the project .venv:

    .venv\Scripts\python.exe -m pip install -e ".[article-summary-tts]"

The selected provider, voice, rate, pitch, volume and no-fallback policy are recorded in `configs/article_summary_tts.json`. The current calibrated default is Edge-TTS at `rate=+5%`, `volume=+0%`, and `pitch=+0Hz`. Manual rate adjustment is bounded at +8%; the engine does not automatically change rate to force a duration pass. The one-minute preflight validates both script character range and the estimated total duration before the online synthesis request. The 58–62 second release gate then uses the normalized PCM sample clock, not estimated text length. There are no automatic network retries and no silent fallback to MeloTTS. A provider/network failure stops the run with an explicit error.

MeloTTS remains available only as a deliberate local alternative by changing `default_provider` to `melo_onnx`; that choice requires the existing Chinese ONNX model and sherpa-onnx runtime. The 58–62 second profile currently has a measured Edge-TTS calibration only; selecting MeloTTS for this delivery target is blocked until its speaking-rate calibration is measured and added explicitly. Do not set an automatic fallback provider.

Generate a local review sample:

    .venv\Scripts\python.exe -X utf8 -m wechat_video.cli run-article-summary --article-dir "path\to\article-package" --summary "path\to\summary.json"

The audio clock is audio-first: after synthesis, each normalized WAV is inspected for its actual PCM sample count. `timeline.py` assembles the narration and derives every speech-unit start/end boundary from those samples; FFprobe durations are retained as diagnostics, not used to override sample timing. A timeline validator rejects gaps, overlaps, inconsistent cue boundaries, or a mismatch between the summed segments and the total sample count before rendering.

The output is a new folder under outputs/ and includes:

- final.mp4, narration.wav, and audio/*.wav
- captions.srt and captions.ass
- article_summary_manifest.json and article_scene_spec.json
- audio_manifest.json, audio_timeline_validation.json, and duration_budget_report.json (selected TTS provider, per-unit audio measurements, preflight estimate, measured duration and sample-clock validation)
- source/article.md, source/article.json, source/images.json, and copied local images
- channels_draft.json, qa_report.json, content_qa_report.json, review_status.json, and REVIEW.md

The visual identity is a premium editorial science documentary: warm paper background, dark editorial typography, original article imagery, concise data panels, visual comparisons, and mechanism diagrams. It does not reuse the current particle-comparison opening or the existing critical-nucleus Manim scene.

## 5. Evidence and quality gates

The CLI refuses to render unless:

1. The article package is marked published and its account is exactly 「成核生长」.
2. If a canonical URL is present, it is verified as an mp.weixin.qq.com/s/... link with recorded read-only provenance. A missing URL is allowed only for local preview and is explicitly recorded as unverified.
3. The summary source hash matches the article Markdown.
4. Every claim excerpt is found verbatim in the original Markdown.
5. Every spoken unit maps to claims and exactly one visual beat.
6. Every original image is local, unique, path-contained, and linked to a source caption/context.
7. The script length and measured TTS duration pass their limits.
8. Technical video QA passes the existing portrait, frame-rate, audio and synchronization checks.

A duplicate article ID is blocked if a prior article-summary run already exists.

## 6. Article source identity, fixed CTA and draft upload

The source article URL remains optional metadata. If a verified canonical URL is available in the source package, it is preserved in the local source record for provenance. It is **not** sent to the Channels extended-link control and is not required for draft upload. A URL must never be constructed from appmsgid.

The final 1.8-second outro renders the fixed message:

**更多详细解读见【成核生长】同名公众号**

The text is part of the video itself, not a clickable link. The 1.8 seconds are included in the measured PCM timeline and exact final-frame budget.

The daily literature pipeline is allowed to upload the exact article-summary run only when:
- `qa_report.json` reports strict PASS;
- the source article ID in the manifest, source record and summary agree;
- every claim excerpt is an exact excerpt from the original article Markdown;
- every claim is linked to a speech unit and every beat is linked to a speech unit;
- audio-timeline, subtitle-coverage, scene-layout and outro-CTA checks pass;
- `channels_draft.json` matches the deterministic metadata derived from the original article and summary.

The shared uploader uses the exact run directory and retains its existing target-account check, single-save behavior, duplicate protection and DraftListManager readback. It never clicks Publish, Send or Schedule. A successful save is reported only after exactly one new unpublished draft row is verified.

Automated source-excerpt and structure checks do not replace the user's scientific review or viewing of the final MP4. The video remains an unpublished draft pending the user's final inspection and manual publication decision.


## Audiovisual pacing and delivery-quality contract

The article-summary path uses one measured PCM sample clock for speech, captions,
scene transitions, the opening and the ending. The following checks are part of
the reusable production path; they are not per-video editing instructions.

### Narration and caption timing

- Edge-TTS is requested with `WordBoundary` metadata in the same synthesis call
  that produces each speech-unit audio file. Metadata offsets are converted from
  100-nanosecond ticks to milliseconds relative to the normalized WAV.
- Word-boundary text must cover the exact `spoken_text` after whitespace
  normalization. Missing, malformed or incomplete metadata is recorded; captions
  then use the measured speech-unit envelope rather than fabricated word timings.
- Captions are grouped into short phrases (normally no more than 12 CJK
  characters per cue), split at punctuation or a 2.2-second reading window, and
  constrained to the corresponding measured speech interval.
- Any cue containing fewer than five Han characters is merged with the nearest
  adjacent cue in the same speech unit. A fragment is never merged across a
  speech-unit boundary or assigned invented timestamps.
- Trailing Chinese/Western commas and full stops are removed from the visual
  caption only. Original spoken text, punctuation restoration and WordBoundary
  timing remain unchanged in the evidence/timing records.
- The mobile caption profile defaults to charcoal `#222222`, 1.18× the
  configured CJK base font size, and zero outline/shadow on the warm-paper
  background. Font size, colour, threshold and decoration remain configurable.
- The default inter-unit pause is 500 ms. Explicit pauses shorter than 450 ms are
  raised to the 450 ms comprehension minimum and retained in the rhythm report as
  requested versus effective values.
- Speech WAV edge treatment is asymmetric (2 ms onset / 10 ms release) to avoid
  unnecessarily attenuating the first consonant. Editorial SFX are delayed from
  the speech onset and remain within their corresponding speech interval.

### Mobile-first figure, cover and sparse-page layouts

- The cover does not repeat the full article title as a tiny kicker above the
  main headline. Any optional kicker must add distinct information rather than
  duplicate the title, source or brand.
- Sparse `hook` and `takeaway` beats use a large, centered statement-card
  template so the visual mass remains balanced on a 9:16 phone screen.
- Four-step mechanism beats use a 2×2 grid. Two- and three-step mechanisms use
  responsive layouts with the same sequence order. The existing timed highlight
  advances in the original speech order; changing geometry never changes event
  timing.
- Figure display crops are declared per image using normalized
  `display_crop_regions`. A crop applies only to the rendered display copy;
  the original locally exported image and its checksum remain untouched.
  `focus_regions` are measured relative to the displayed crop. The crop plan
  must preserve axes, legends, units and data marks; the renderer must not
  guess a crop from a caption or blindly trim the image bottom.
- Optional `axis_labels_zh` supplies concise `x` and/or `y` labels per
  selected image. These labels must be grounded in the figure and article
  evidence. The engine renders supplied labels but never invents scientific
  variable meanings or hardcodes a project-specific translation.

### Visual rhythm, safe areas and opening/ending

- Cover fade-in time is included inside the configured cover duration. The first
  visual transition uses the final cover interval, ending at the first narration
  boundary; subsequent transitions are placed in the available inter-unit pause
  wherever that pause is long enough.
- Mechanism cards advance their focus one step at a time. Comparison panels,
  statistic values and figure focus areas receive restrained, timed emphasis.
- Scene core content is checked against the portrait frame and the configured
  subtitle safe band. The Manim render must produce
  `scene_layout_report.json`; a failed or missing report blocks final assembly.
- A minimum 1,800 ms outro segment is included in the measured audio clock. The literature-reading end card remains visible through the final frame; its CTA text is rendered as video content, not a platform link.
- The original deterministic editorial music bed is active on cover, speech and
  outro, ducked under narration, and absent from intentional inter-unit silence.
  The mix report measures cover/outro music and verifies that inter-unit gaps
  remain near digital silence.

### Exact final video frame budget

The Manim scene may finish a small number of frames before the audio-derived
programme boundary because individual scene timings are quantized to video
frames. Final assembly therefore converts to the target constant frame rate,
clones the final scene frame only when needed (with a strict six-frame maximum),
and then trims to the exact frame count calculated from the global PCM sample
clock. A larger scene deficit fails rather than being hidden by a long frozen
tail. The video-only encode and
the final stream-copy mux are both probed and must contain exactly that frame
count. The mux does not use `-shortest`, which could discard a valid final
video frame when the audio duration falls fractionally before the rounded video
frame boundary. QA continues to require an exact frame-count match; no tolerance
or duration threshold is relaxed.

### Duration budget and plain-language narration

- The configured one-minute profile records its target (60 seconds), release
  interval (58–62 seconds), calibrated CJK character range (222–235), and
  expected spoken-character rate in `configs/article_summary_tts.json`.
  These are planning estimates only; measured PCM duration remains authoritative.
- Script-length and estimated-duration preflight happen before Edge-TTS is
  called. After synthesis, the measured complete programme must be 58–62
  seconds. An out-of-range result stops before Manim rendering and writes
  `duration_budget_report.json`; there is no silent retry or speed-up loop.
- To improve audience comprehension, the content plan may introduce a
  plain-language gloss before or alongside a technical term. This is a
  presentation transformation, not permission to change scientific meaning.
  Quantitative values, units, experimental conditions, mechanisms, comparisons,
  uncertainty and limitations must remain traceable to the existing claims.
  When a concept cannot be simplified without changing its meaning, retain the
  term and explain it briefly instead of substituting an inaccurate analogy.
- Length is reduced by removing repetition and rewriting dense syntax, not by
  dropping evidence-backed results. If the target cannot be met without losing
  a material claim, the plan must report that conflict rather than force a
  one-minute cut.

### Automated delivery artifacts

Each local run records:

- `audio_manifest.json`: provider, voice, normalized WAV samples, word-boundary
  status and alignment metadata.
- `audio_timing.json` and `audio_timeline_validation.json`: a contiguous,
  sample-count-derived timeline including the outro.
- `captions.srt`, `captions.ass`, and `subtitle_alignment`: phrase-level
  caption text, time bounds and alignment method.
- `narration_rhythm_report.json`: unit-length, punctuation and pause diagnostics.
  It is diagnostic only and never rewrites scientific narration.
- `scene_layout_report.json`: per-beat camera bounds and subtitle safe-band checks.
- `audio_mix_report.json`: measured music activity at cover/outro and true-silence
  diagnostics for inter-unit pauses.
- `content_qa_report.json`, `qa_report.json`, and `REVIEW.md`: source,
  timeline, captions, visual layout, audio mix and technical delivery status.

Automated QA is a release gate for structural and technical defects, not a
replacement for listening to the voice, judging scientific fidelity, or the
user's final visual review. Every output remains local-preview-only; no channel
upload or publication is performed by this workflow.
