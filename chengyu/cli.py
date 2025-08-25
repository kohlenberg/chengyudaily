import argparse, sys
from .config import settings
from .dedupe import list_existing_chengyu
from .gen import gen_unique_episode_strict, gen_episode_for, script_to_markdown
from .cover import draw_cover_png
from .tts import tts_mp3
from .publisher import publish_episode
from .utils import normalize_chengyu

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="chengyudaily",
        description="Generate & publish a unique Chengyu podcast episode."
    )
    p.add_argument("--episode", help="Explicit idiom to use (Chinese characters). Skips uniqueness sampling.")
    p.add_argument("--skip-tts", action="store_true", help="Generate post & cover only (no audio).")
    p.add_argument("--dry-run", action="store_true", help="Do everything except pushing to GitHub.")
    p.add_argument("--batch-size", type=int, default=20, help="How many candidates to request per round.")
    p.add_argument("--max-rounds", type=int, default=20, help="How many rounds to try for a unique idiom.")
    p.add_argument("--model", help="Override GEN_MODEL at runtime.")
    p.add_argument("--voice", help="Override TTS_VOICE at runtime.")
    args = p.parse_args(argv)

    gen_model = args.model or settings.GEN_MODEL
    tts_model = settings.TTS_MODEL
    voice = args.voice or settings.TTS_VOICE
    really_dry = args.dry_run or settings.DRY_RUN

    print(f"Show: {settings.SHOW_NAME}")
    print(f"Repo: {settings.REPO}@{settings.GITHUB_BRANCH}")
    print(f"Mode: {'DRY RUN' if really_dry else 'PUBLISH'}")
    print()

    # 0) already-used idioms
    seen = list_existing_chengyu(settings.REPO, settings.GITHUB_BRANCH)

    # 1) pick/generate episode data
    if args.episode:
        if normalize_chengyu(args.episode) in seen:
            print(f"ERROR: '{args.episode}' already exists. Choose another.")
            sys.exit(2)
        data = gen_episode_for(settings.SHOW_NAME, gen_model, args.episode)
    else:
        data = gen_unique_episode_strict(
            settings.SHOW_NAME, gen_model, seen,
            batch_size=args.batch_size, max_rounds=args.max_rounds
        )

    print(f"Selected idiom: {data['chengyu']} ({data['pinyin']})")
    print(f"Teaser: {data['teaser']}")
    print()

    # 2) cover
    cover_png = draw_cover_png(settings.SHOW_NAME, data["chengyu"], data["pinyin"], data["gloss"])

    # 3) TTS
    audio_mp3 = None
    if not args.skip_tts:
        print("Generating TTS…")
        audio_mp3 = tts_mp3(data["script"], tts_model, voice)

    # 4) format post body (Markdown)
    body_md = script_to_markdown(
        data["chengyu"], data["pinyin"], data["gloss"], data["teaser"], data["script"], gen_model
    )

    # 5) publish (single commit)
    res = publish_episode(
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
        dry_run=really_dry,
    )
    print("\nDone:", res)

if __name__ == "__main__":
    main()
