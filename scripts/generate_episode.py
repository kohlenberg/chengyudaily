#!/usr/bin/env python3
import os, sys, datetime
from pathlib import Path

from chengyu.publisher import publish_episode
from chengyu.cover_flow import make_cover_bytes
from chengyu.config import settings
from chengyu.dedupe import list_existing_chengyu
from chengyu.gen import gen_unique_episode_strict, script_to_markdown
from chengyu.tts import tts_mp3

def main():

    # 0) Unique generation
    forbidden = list_existing_chengyu(settings.REPO, settings.GITHUB_BRANCH)
    data = gen_unique_episode_strict(
        settings.SHOW_NAME, settings.GEN_MODEL, forbidden,
        batch_size=20, max_rounds=20
    )

    # 1) Cover (hybrid + dark-top safety)
    cover_bytes, cover_ext = make_cover_bytes(
        data, attempts=4, out_format="JPEG"  # fast-ish; tweak attempts if needed
    )

    # 2) Audio (TTS)
    audio_mp3 = tts_mp3(data["script"], settings.TTS_MODEL, settings.TTS_VOICE)

    # 3) Markdown body
    body_md = script_to_markdown(
        data["chengyu"], data["pinyin"], data["gloss"], data["teaser"], data["script"], settings.GEN_MODEL
    )

    # 4) Publish
    publish_episode(
        show_name=settings.SHOW_NAME,
        repo=settings.REPO,
        branch=settings.GITHUB_BRANCH,
        site_url=settings.SITE_URL,
        baseurl=settings.BASEURL,
        publish_time_utc=settings.PUBLISH_TIME_UTC,
        data=data,
        body_md=body_md,
        cover_bytes=cover_bytes,
        cover_ext=cover_ext,            # "jpg" or "png"
        audio_mp3=audio_mp3,
        upload_audio_to_release=True,   # << Release asset = faster pushes
        write_audio_to_repo=True,      # << don’t commit MP3 into repo
        dry_run=settings.DRY_RUN,
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())
