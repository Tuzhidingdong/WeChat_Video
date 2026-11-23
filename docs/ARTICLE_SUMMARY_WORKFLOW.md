# 「精读一分钟」文章摘要视频工作流

**Status:** local preview pipeline implemented; article URL export and WeChat Channels extended-link UI remain unverified.

## 1. Product boundary

「精读一分钟」 is a separate Chinese-language content type. Its source is an article that has already been published by the 「成核生长」 WeChat Official Account. It is not a shortened version of the critical-nucleus explainer series.

The pipeline consumes a sanitized, local article package exported by the publishing workflow. The package must identify the article as Slot 1 with editorial_pillar_id set to literature_translation. It does not access or reuse the WeChat_control browser profile, cookies, access tokens, or private platform APIs. This keeps the Video project isolated from the WeChat_control account session and browser automation.

## 2. Input package contract

Create one directory per published article:

    article-package/
      article.json
      article.md
      images.json
      images/
        IMG01.jpg
        IMG02.png

article.json:

    {
      "schema_version": 1,
      "account_name": "成核生长",
      "editorial_slot": 1,
      "editorial_pillar_id": "literature_translation",
      "publication_status": "PUBLISHED",
      "article_id": "the published appmsg/article identifier",
      "title": "The exact published article title",
      "published_at": "2026-11-21T21:10:55+08:00",
      "canonical_url": "https://mp.weixin.qq.com/s/the-real-published-link",
      "canonical_url_verified": true,
      "url_provenance": {
        "endpoint": "/the/observed/backend/route",
        "field_path": "the.actual.response.field.path",
        "verified_at": "2026-11-23T12:00:00+08:00",
        "read_only": true
      }
    }

The URL must be the exact HTTPS mp.weixin.qq.com/s/... link read from an observed published-article response. Do not construct it from appmsgid. Do not put tokens, cookies, credentials, or authenticated query parameters in the package. The endpoint field is the route only; the field path identifies the actual response property that carried the URL.

article.md is the complete exported article text. images.json uses this structure:

    {
      "images": [
        {
          "image_id": "IMG01",
          "file": "images/IMG01.jpg",
          "image_aspect": 1.5,
          "caption": "A caption found in the article",
          "context": "The article paragraph to which this image belongs"
        }
      ]
    }

Image paths must remain inside the package directory. An image selected for a video beat must have a caption or context that can be found in the article Markdown. Only locally exported original article images are used; the renderer does not fetch third-party images.

## 3. Summary script contract

The model or editor creates a separate summary.json. Its source hash must match article.md. Every claim must include an exact source excerpt, and each spoken unit and visual beat must map to one or more of those claim IDs.

Top-level fields:

- schema_version: 1
- article_id: exact match with article.json
- source_article_sha256: SHA-256 of the exact article.md bytes
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
- image: one or two actual article images, displayed with contain/no crop
- stat: one article-grounded numerical result
- compare: comparison supported by cited claims
- mechanism: two to four explanatory steps
- quote: an exact excerpt from the article
- takeaway: final conclusion and practical meaning

Three consecutive beats may not use the same visual type. Numeric values in stat_value must occur in the article source text. Quoted text must exactly match the article after whitespace normalization.

The spoken script is constrained to 150–360 Chinese characters before TTS. The actual measured audio must be 45–75 seconds. It is never sped up or time-stretched to satisfy the limit.

## 4. Local commands

The default Slice A English voice and its personal OpenVoice profile are unchanged. The article-summary workflow uses the existing offline Chinese MeloTTS zh_en model on CPU. It does not use a cloud TTS service and does not fall back to the English voice.

Check whether the local Chinese model is already available. Only when it is missing, run the existing one-time model command:

    .venv\Scripts\python.exe -X utf8 -m wechat_video.cli download-model-zh

Generate a local review sample:

    .venv\Scripts\python.exe -X utf8 -m wechat_video.cli run-article-summary --article-dir "path\to\article-package" --summary "path\to\summary.json"

The output is a new folder under outputs/ and includes:

- final.mp4, narration.wav, and audio/*.wav
- captions.srt and captions.ass
- article_summary_manifest.json and article_scene_spec.json
- source/article.md, source/article.json, source/images.json, and copied local images
- channels_draft.json, qa_report.json, content_qa_report.json, review_status.json, and REVIEW.md

The visual identity is a premium editorial science documentary: warm paper background, dark editorial typography, original article imagery, concise data panels, visual comparisons, and mechanism diagrams. It does not reuse the current particle-comparison opening or the existing critical-nucleus Manim scene.

## 5. Evidence and quality gates

The CLI refuses to render unless:

1. The article package is marked published and its account is exactly 「成核生长」.
2. The canonical URL is a verified mp.weixin.qq.com/s/... link with recorded read-only provenance.
3. The summary source hash matches the article Markdown.
4. Every claim excerpt is found verbatim in the original Markdown.
5. Every spoken unit maps to claims and exactly one visual beat.
6. Every original image is local, unique, path-contained, and linked to a source caption/context.
7. The script length and measured TTS duration pass their limits.
8. Technical video QA passes the existing portrait, frame-rate, audio and synchronization checks.

A duplicate article ID is blocked if a prior article-summary run already exists.

## 6. Extended-link status and upload safety

channels_draft.json carries the exact article URL, article ID, and title in an extended_link object. This is only a local metadata payload; it does not mean the Channels Assistant has mounted the article card.

**All article-summary runs are explicitly blocked from the existing uploader.** The upload guard remains active until a live, read-only inspection identifies the actual extended-link control and a later authorized test proves that the article link is selected, saved, and read back from the resulting draft. Putting the URL in the ordinary description field is not accepted as a substitute.

The current local audit found the WeChat_control research_subscription session expired. No reliable article URL field was obtained. Accordingly, no URL adapter or field selector is claimed to be production-ready. The publishing workflow must first export a real article package using a verified response field.

No video is uploaded, saved as a draft, or published by run-article-summary. User review of the complete MP4 is required before any future draft-only integration is enabled.
