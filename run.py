from chengyu.config import settings
from chengyu.dedupe import list_existing_chengyu
from chengyu.gen import gen_unique_episode_strict, script_to_markdown
from chengyu.cover import draw_cover_png
from chengyu.tts import tts_mp3
from chengyu.publisher import publish_episode

# 0) Already-used idioms (full set)
forbidden = list_existing_chengyu(settings.REPO, settings.GITHUB_BRANCH)

# 1) Strict-unique generation
data = gen_unique_episode_strict(settings.SHOW_NAME, settings.GEN_MODEL, forbidden,
                                 batch_size=20, max_rounds=20)

# 2) Cover image
cover_png = draw_cover_png(settings.SHOW_NAME, data["chengyu"], data["pinyin"], data["gloss"])

# 3) TTS (disable by setting SKIP_TTS=True)
SKIP_TTS = False
audio_mp3 = None if SKIP_TTS else tts_mp3(data["script"], settings.TTS_MODEL, settings.TTS_VOICE)

# 4) Structured Markdown body
body_md = script_to_markdown(data["chengyu"], data["pinyin"], data["gloss"], data["teaser"], data["script"], settings.GEN_MODEL)

# 5) Publish
publish_episode(
    show_name=settings.SHOW_NAME,
    repo=settings.REPO,
    branch=settings.GITHUB_BRANCH,
    site_url=settings.SITE_URL,
    baseurl=settings.BASEURL,
    publish_time_utc=settings.PUBLISH_TIME_UTC,
    data=data,
    body_md=body_md,
    cover_png=cover_png,
    audio_mp3=audio_mp3,
    dry_run=settings.DRY_RUN,
)
