import os
import time
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from openai import OpenAI

from proxy_utils import normalize_proxy_environment

load_dotenv(override=True)
normalize_proxy_environment()

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
TELEGRAM_SUMMARY_MAX_CHARS = int(os.getenv("TELEGRAM_SUMMARY_MAX_CHARS", "3300"))


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


def summarize_article_for_telegram(
    title: str,
    body: str,
    source_url: str,
    target_language: str = TARGET_LANGUAGE,
    max_chars: int = TELEGRAM_SUMMARY_MAX_CHARS,
) -> str:
    """
    Summarize an article into one Telegram-safe message.
    """
    source_block = f"\n\nSource URL:\n{source_url}" if source_url else ""
    available_chars = max(1200, max_chars - len(source_block) - 40)
    article_text = f"Title:\n{title or ''}\n\nArticle:\n{body or ''}".strip()

    prompt = f"""Summarize the following article into {target_language} for a Telegram channel.

Rules:
- The final answer must be under {available_chars} characters.
- Write one clear translated headline first.
- Then write a concise news summary in 3 to 6 short bullet points.
- Keep the most important facts, names, numbers, dates, locations, and consequences.
- Do not add facts that are not in the article.
- Do not include introductions like "here is the summary".
- Use a clear journalistic tone.

Article:

{article_text}
"""

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            summary = response.choices[0].message.content.strip()
            if len(summary) > available_chars:
                summary = summary[:available_chars].rsplit("\n", 1)[0].strip()
            if source_url:
                summary = f"{summary}\n\nمنبع اصلی:\n{source_url}"
            return summary.strip()

        except Exception as e:
            if attempt == 2:
                message = str(e)
                if PROVIDER == "gapgpt" and "quota exhausted" in message.lower():
                    raise RuntimeError(
                        "GapGPT token quota exhausted. Update GAPGPT_API_KEY or top up the token quota."
                    ) from e
                raise RuntimeError(f"Summarization failed: {e}")

            time.sleep(2)

    return ""


def translate_article(title: str, body: str, source_url: str) -> str:
    return summarize_article_for_telegram(title, body, source_url)
