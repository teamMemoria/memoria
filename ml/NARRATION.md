# Local natural narration

The Communication style Evidence card uses the same Kokoro-82M v1.0 model,
kokoro-onnx 0.6.1 runtime, speed (1.0), language (en-us) and MP3 normalization
as the original Communication style mock. This is generated narration of the
displayed transcript, not original audio, voice identity, emotion evidence
or an input to scoring. System actions are never spoken as dialogue.

| Role | Masculine demo voice | Feminine demo voice |
| --- | --- | --- |
| Agent | Michael (`am_michael`) | Bella (`af_bella`) |
| Customer | Fenrir (`am_fenrir`) | Heart (`af_heart`) |

The frontend retains its name-based demo casting conventions; ambiguous Agent
names use the existing default. The API has no separate customer-profile field,
so Customer uses the existing Heart default. No gender field is added.
The removed Voice settings and Calculation and evidence sections stay removed.

## Preparation

Runtime files, exported text, generated assets and failure history live under
ignored `ml/output/narration/`. They are not public frontend assets. Use an
isolated Python 3.11 environment with `kokoro-onnx==0.6.1`, `soundfile==0.13.1`
and local ffmpeg. No application runtime dependencies or paid APIs are added.
Download `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the same release as the mock:
https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1
The generator requires the exact original hashes in `backend.services.narration`.
Model weights are Apache 2.0; kokoro-onnx is MIT. Retain upstream licences with
local model/runtime files when redistributing them.

Export only the authorized training conversations through the existing
read API. The JSON list contains `id`, `sourceId`, `agentId`, `agentName`,
`version`, `turns` (the API transcript turns), and `voices` (role to preset ID).
Verify the source IDs against `ml/rule_cohort.json`; never load held-out data or
raw dataset answer labels. Then run from the repository root:

```sh
PYTHONPATH=backend/src ml/output/narration/.venv/bin/python \
  ml/generate_narration.py ml/output/narration/export.json \
  ml/output/narration/models ml/output/narration/clips
```

The generator reuses hash-verified clips, retains old assets and appends errors
to `failures.jsonl`. Run again to resume after interruption. Optional `--shard N
--shards M` partitions unique clip keys for independent local processes; use the
same M for every shard. `--all-voices` can prepare both role voices if future
explicit casting requires them. The current cohort needs its assigned voices only.

## Serving and playback

Agent and Manager narration endpoints reuse their existing conversation access
checks. The client submits turn number, voice ID and SHA-256 of the exact displayed
text, not raw text. The server reads that authorized canonical turn, checks its
hash and role, then validates the cached recipe, exact text and MP3 hash.
It returns private, no-store audio; it never generates or writes assessment data.
Missing/damaged clips return 503, stale displayed text 409, inaccessible calls 404.
There is no browser-voice or fictional-recording fallback.

Enable Demo voice once, then hover for 300 ms or focus/tap a turn. Only that
passage plays. Leaving, muting, Escape, tab hiding and navigation stop playback
and abort pending requests. One reusable media element supports Safari's user
activation rules. The playhead uses actual MP3 playback time; the bar shapes
remain text-derived. Cached browser blobs are scoped to the mounted conversation
and viewer and are released when navigating away.

Changing text, role, voice, model, runtime recipe or encoding invalidates affected
clip keys. Generated durations describe the narration only, never the original
conversation duration.

## Original-text demo (2026-11-12)

At the user's request, the frozen 117 training conversations now use original
source text for transcripts, exact citations, draft passages and narration.
`unmasked-demo-v1` binds this representation into the transcript hash and is
restricted to training evidence. Other imports retain their existing defaults.

The approved v13 assessments were originally recognized using masked text.
`restore_demo_text` verifies that the original record reproduces that exact
historical input, then restores only whole-turn citations. Scores, coverage,
interpretation limits and approvals remain unchanged. Each restored report
records the original report hash and recognition transcript version; it does
not claim to be a fresh assessment of unmasked text. Both representations were
validated with the original approved rules and references.

The source file hash was checked and only the training array was parsed. The
local restoration artifacts, before/after database snapshots, original reports
and audio export are retained under `ml/output/unmasked-demo-20261112/`.
Historical analysis runs and audio clips are preserved. Changed text gets new
clip identities; stale browser text cannot play the old clip as current audio.
