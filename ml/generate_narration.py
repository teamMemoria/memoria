"""Generate private local narration from an exported, already masked cohort.

PYTHONPATH=backend/src <voice-venv>/bin/python ml/generate_narration.py export.json models clips
Optional --all-voices prepares both role voices; otherwise use exported demo casting.
No dataset loader, model API, raw input, assessment or approval writes.
"""

import argparse
import hashlib
import importlib.metadata
import json
import logging
import subprocess
import tempfile
from pathlib import Path

from backend.services.narration import (
    MODEL_SHA256,
    ROLE_VOICES,
    VOICES_SHA256,
    clip_identity,
    clip_key,
    read_clip,
)


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("export", type=Path)
    args.add_argument("models", type=Path)
    args.add_argument("output", type=Path)
    args.add_argument("--all-voices", action="store_true")
    args.add_argument("--shard", type=int, default=0)
    args.add_argument("--shards", type=int, default=1)
    args = args.parse_args()
    if not 0 <= args.shard < args.shards:
        raise ValueError("Require 0 <= shard < shards")
    if importlib.metadata.version("kokoro-onnx") != "0.6.1":
        raise ValueError("Use the verified mock runtime kokoro-onnx 0.6.1")
    for name, digest in [
        ("kokoro-v1.0.onnx", MODEL_SHA256),
        ("voices-v1.0.bin", VOICES_SHA256),
    ]:
        if hashlib.sha256((args.models / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Mock model pin mismatch: {name}")
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    from kokoro_onnx import Kokoro

    data = json.loads(args.export.read_text())
    jobs = {}
    for call in data:
        for turn in call["turns"]:
            role = turn["speaker"]
            if role not in ROLE_VOICES or not turn["text"].strip():
                continue
            voices = ROLE_VOICES[role] if args.all_voices else [call["voices"][role]]
            for voice in voices:
                identity = clip_identity(turn["text"], role, voice)
                jobs[clip_key(identity)] = identity
    jobs = {
        key: value
        for key, value in jobs.items()
        if int(key, 16) % args.shards == args.shard
    }
    args.output.mkdir(parents=True, exist_ok=True)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(args.models / "kokoro-v1.0.onnx"),
        options,
        providers=["CPUExecutionProvider"],
    )
    kokoro = Kokoro.from_session(session, str(args.models / "voices-v1.0.bin"))
    failures = []
    for index, (key, identity) in enumerate(jobs.items(), 1):
        if read_clip(args.output, identity) is not None:
            print(f"{index}/{len(jobs)} reused {key[:12]}", flush=True)
            continue
        try:
            samples, rate = kokoro.create(
                identity["text"], voice=identity["voice"], speed=1.0, lang="en-us"
            )
            duration = len(samples) / rate
            if (
                not np.isfinite(samples).all()
                or duration <= 0.25
                or np.max(np.abs(samples)) <= 0.01
            ):
                raise ValueError("Invalid or empty generated audio")
            with tempfile.TemporaryDirectory(prefix="memoria-narration-") as temp:
                wav, mp3 = Path(temp) / "voice.wav", Path(temp) / "voice.mp3"
                sf.write(wav, samples, rate)
                subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(wav),
                        "-af",
                        f"loudnorm=I=-18:TP=-1.5:LRA=7,afade=t=in:d=0.008,afade=t=out:st={max(0, duration - 0.015)}:d=0.015",
                        "-ar",
                        "24000",
                        "-ac",
                        "1",
                        "-codec:a",
                        "libmp3lame",
                        "-b:a",
                        "96k",
                        str(mp3),
                    ],
                    check=True,
                    capture_output=True,
                )
                content = mp3.read_bytes()
            metadata = {
                "identity": identity,
                "sha256": hashlib.sha256(content).hexdigest(),
                "durationSeconds": duration,
                "synthetic": True,
            }
            # The manifest is the completion marker; interrupted clips are not reusable.
            (args.output / f"{key}.mp3").write_bytes(content)
            pending = args.output / f"{key}.json.tmp"
            pending.write_text(json.dumps(metadata, ensure_ascii=False) + "\n")
            pending.replace(args.output / f"{key}.json")
            print(
                f"{index}/{len(jobs)} generated {key[:12]} {duration:.2f}s", flush=True
            )
        except Exception as error:
            logging.getLogger(__name__).exception("Narration generation failed for %s", key)
            failure = {"key": key, "error": str(error)}
            failures.append(failure)
            with (args.output / "failures.jsonl").open("a") as history:
                history.write(json.dumps(failure) + "\n")
            print(f"{index}/{len(jobs)} FAILED {key[:12]} {error}", flush=True)
    print(json.dumps({"clips": len(jobs), "failures": failures}), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
