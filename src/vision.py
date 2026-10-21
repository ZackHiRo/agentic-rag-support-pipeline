"""Verbatim transcription of screenshots via an OpenAI vision-capable model.

The agent pipeline is text-only: classifier, hybrid retrieval, and drafting
all expect a string. To accept screenshots without disturbing any of that,
this module converts each image to verbatim text in a single cheap call,
preserving the original language so the downstream language-matching rule
in prompts/system.md still works.

Usage:
    from src.vision import transcribe_screenshots
    text = transcribe_screenshots([image_bytes_1, image_bytes_2])
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# gpt-4.1-mini supports vision and is ~10x cheaper than gpt-4.1. Override via
# .env if you need a different model (any vision-capable model works).
VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")

# OpenAI's "high" detail tier expects images at most 1568x1568. Resizing
# screenshots locally before upload caps the per-image input cost and avoids
# bandwidth waste on large desktop captures (often 2560x1440 or 3840x2160).
MAX_IMAGE_DIM = 1568

VISION_SYSTEM_PROMPT = (
    "You transcribe screenshots for a support-ticket triage system. Rules:\n"
    "1. Output a VERBATIM transcription of all readable text in the image. "
    "Do NOT summarize, translate, or paraphrase.\n"
    "2. Preserve the original language exactly (English, French, etc.).\n"
    "3. Preserve UI labels, button text, error codes, IDs, timestamps, "
    "usernames, account IDs, ticket IDs, dates, and amounts EXACTLY as shown.\n"
    "4. Use plain text. Preserve line breaks and obvious structure (lists, "
    "form fields). Use 'Label: value' for form-style screenshots.\n"
    "5. If a screenshot has no readable text or is unreadable (blurry, "
    "blank, decorative), output exactly: [unreadable]\n"
    "6. When multiple images are provided, prefix each transcription with a "
    "header line: [Screenshot k of N] (using 1-based indexing).\n"
    "7. Briefly describe non-text visual elements that carry meaning for "
    "support context (e.g. 'screenshot shows red error dialog', 'screenshot "
    "shows in-game store with item highlighted'). Keep these notes terse "
    "and label them with a leading [visual]: tag so the agent can tell them "
    "apart from literal on-screen text.\n"
    "Do not add any other commentary."
)


def _resize_to_data_url(image_bytes: bytes) -> str:
    """Resize an image to fit within MAX_IMAGE_DIM (preserving aspect ratio)
    and return a base64 data URL suitable for the OpenAI vision API."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = img.convert("RGB") if img.mode in ("RGBA", "P", "LA") else img
        if max(img.size) > MAX_IMAGE_DIM:
            img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def transcribe_screenshots(
    images: list[bytes],
    *,
    model: str | None = None,
) -> str:
    """Return a verbatim transcription of one or more screenshot images.

    Preserves the original language. Returns ``""`` if `images` is empty so
    callers can pass it unconditionally. Multiple images are joined with a
    clear ``[Screenshot k of N]`` header per image (the model is instructed
    to add these). On error, returns a string starting with ``[vision error]``
    so the caller can surface it without blowing up the whole run.
    """
    if not images:
        return ""

    try:
        data_urls = [_resize_to_data_url(b) for b in images]
    except Exception as exc:
        return f"[vision error] failed to read attached image(s): {exc}"

    user_content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Transcribe the following {len(images)} screenshot(s) per "
                f"the rules. Return only the transcription."
            ),
        }
    ]
    for url in data_urls:
        user_content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})

    client = OpenAI()
    try:
        resp = client.chat.completions.create(
            model=model or VISION_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
    except Exception as exc:
        return f"[vision error] transcription request failed: {exc}"

    text = (resp.choices[0].message.content or "").strip()
    return text or "[unreadable]"
