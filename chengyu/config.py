# chengyu/config.py
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    SHOW_NAME: str = os.getenv("SHOW_NAME", "Chengyu Bites")

    GEN_MODEL: str = os.getenv("GEN_MODEL", "gpt-4o-mini")
    TTS_MODEL: str = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
    TTS_VOICE: str = os.getenv("TTS_VOICE", "alloy")
    # chengyu/config.py (add near other fields)
    IMAGE_MODEL: str = os.getenv("IMAGE_MODEL", "gpt-image-1")
    IMAGE_SIZE: int = int(os.getenv("IMAGE_SIZE", "2048"))  # 1024 or 2048 are safe

    REPO: str = os.getenv("REPO", "kohlenberg/chengyudaily")
    GITHUB_BRANCH: str = os.getenv("GITHUB_BRANCH", "main")

    SITE_URL: str = os.getenv("SITE_URL", "https://kohlenberg.github.io")
    BASEURL: str = os.getenv("BASEURL", "/chengyudaily")
    PUBLISH_TIME_UTC: str = os.getenv("PUBLISH_TIME_UTC", "10:00:00 +0000")

    DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() == "true"

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

# export a ready-to-use instance
settings = Settings()
