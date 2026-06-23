import os
import time
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SHELL_ENV_KEYS = {
    "GAPGPT_API_KEY",
    "GAPGPT_BASE_URL",
    "GAPGPT_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "TRANSLATION_TARGET_LANGUAGE",
}


def _load_shell_env_file(path: Path) -> None:
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if key not in SHELL_ENV_KEYS or key in os.environ:
            continue

        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()

        os.environ[key] = value


_load_shell_env_file(Path.home() / ".zshrc")

# Use gapgpt API if available, fall back to OpenAI
GAPGPT_API_KEY = os.getenv("GAPGPT_API_KEY")
GAPGPT_BASE_URL = os.getenv("GAPGPT_BASE_URL", "https://api.gapgpt.app/v1")
GAPGPT_MODEL = os.getenv("GAPGPT_MODEL", "gapgpt-qwen-3.5")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")

TARGET_LANGUAGE = os.getenv("TRANSLATION_TARGET_LANGUAGE", "Persian")


# Prefer gapgpt if API key is available
if GAPGPT_API_KEY:
    PROVIDER = "gapgpt"
    client = OpenAI(
        api_key=GAPGPT_API_KEY,
        base_url=GAPGPT_BASE_URL,
    )
    MODEL = GAPGPT_MODEL
    print(f"[TRANSLATOR] Using gapgpt at {GAPGPT_BASE_URL} (model: {MODEL})")
elif OPENAI_API_KEY:
    PROVIDER = "openai"
    client = OpenAI(
        api_key=OPENAI_API_KEY,
    )
    MODEL = OPENAI_MODEL
    print(f"[TRANSLATOR] Using OpenAI (model: {MODEL})")
else:
    raise RuntimeError("No translator API key configured. Set GAPGPT_API_KEY or OPENAI_API_KEY.")


def split_text(text: str, max_chars: int = 6000) -> List[str]:
    """
    Splits long articles into safe chunks by paragraph.
    This prevents API/context/message-size problems.
    """
    paragraphs = text.split("\n")
    chunks = []
    current = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(current) + len(paragraph) + 2 <= max_chars:
            current += paragraph + "\n\n"
        else:
            if current.strip():
                chunks.append(current.strip())
            current = paragraph + "\n\n"

    if current.strip():
        chunks.append(current.strip())

    return chunks


def translate_text(text: str, target_language: str = TARGET_LANGUAGE) -> str:
    """
    Translates article text while preserving meaning, structure, and factual neutrality.
    Uses chat completions API (compatible with gapgpt and OpenAI).
    """
    if not text or not text.strip():
        return ""

    chunks = split_text(text)
    translated_chunks = []

    for index, chunk in enumerate(chunks, start=1):
        prompt = f"""Translate the following article content into {target_language}.

Rules:
- Translate the full text accurately.
- Do not summarize.
- Do not add new facts.
- Preserve paragraph structure.
- Preserve names, companies, products, numbers, dates, and URLs.
- Use a clear journalistic tone.
- If the original text has a title, translate it naturally.

Article part {index}/{len(chunks)}:

{chunk}
"""

        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                )

                translated_chunks.append(response.choices[0].message.content.strip())
                break

            except Exception as e:
                if attempt == 2:
                    message = str(e)
                    if PROVIDER == "gapgpt" and "quota exhausted" in message.lower():
                        raise RuntimeError(
                            "GapGPT token quota exhausted. Update GAPGPT_API_KEY or top up the token quota."
                        ) from e
                    raise RuntimeError(f"Translation failed on chunk {index}: {e}")

                time.sleep(2)

    return "\n\n".join(translated_chunks)


def translate_article(title: str, body: str, source_url: str) -> str:
    translated_title = translate_text(title) if title else ""
    translated_body = translate_text(body)

    final_message = ""

    if translated_title:
        final_message += f"{translated_title}\n\n"

    final_message += translated_body.strip()

    if source_url:
        final_message += f"\n\nمنبع اصلی:\n{source_url}"

    return final_message
