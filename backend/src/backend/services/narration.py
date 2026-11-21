"""Private, content-bound generated narration; never original call evidence."""

import hashlib
import json
from pathlib import Path

MODEL_SHA256 = "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a"
VOICES_SHA256 = "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
RECIPE = {
    "model": MODEL_SHA256,
    "voices": VOICES_SHA256,
    "runtime": "kokoro-onnx 0.6.1",
    "speed": 1.0,
    "language": "en-us",
    "encoding": "mp3-24k-mono-96k-loudnorm-18-v1",
}
ROLE_VOICES = {
    "Agent": ("am_michael", "af_bella"),
    "Customer": ("am_fenrir", "af_heart"),
}
DEFAULT_CACHE = Path(__file__).resolve().parents[4] / "ml/output/narration/clips"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clip_identity(text: str, speaker: str, voice: str) -> dict:
    if voice not in ROLE_VOICES.get(speaker, ()) or not text.strip():
        raise ValueError("No narration for this speaker or voice")
    return {"text": text, "speaker": speaker, "voice": voice, "recipe": RECIPE}


def clip_key(identity: dict) -> str:
    return text_hash(json.dumps(identity, ensure_ascii=False, sort_keys=True))


def read_clip(directory: Path, identity: dict) -> bytes | None:
    """Fail closed on missing, stale, damaged or mismatched local assets."""
    key = clip_key(identity)
    try:
        metadata = json.loads((directory / f"{key}.json").read_text())
        if metadata["identity"] != identity:
            return None
        content = (directory / f"{key}.mp3").read_bytes()
        if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
            return None
        return content
    except (OSError, ValueError, KeyError, TypeError):
        return None
