# chengyu/publisher.py
import os, json, shutil, tempfile, datetime
from pathlib import Path
from .utils import slugify, run, normalize_chengyu
from .dedupe import list_existing_chengyu

def _front_matter(obj: dict) -> str:
    import yaml
    return "---\n" + yaml.safe_dump(obj, allow_unicode=True, sort_keys=False).strip() + "\n---\n\n"

def publish_episode(*,
    show_name: str,
    repo: str,
    branch: str,
    site_url: str,
    baseurl: str,
    publish_time_utc: str,
    data: dict,                 # from gen_* (chengyu, pinyin, gloss, teaser, script)
    body_md: str,               # from script_to_markdown
    cover_png: bytes,
    audio_mp3: bytes | None,
    dry_run: bool = False,
):
    today = datetime.datetime.utcnow().date()
    date_str = today.strftime("%Y-%m-%d")
    slug = slugify(data["pinyin"])
    folder = f"{date_str}-{slug}"

    cover_rel = f"/episodes/{folder}/cover.png"
    audio_rel = f"/episodes/{folder}/audio.mp3" if audio_mp3 else ""

    fm = {
        "layout": "post",
        "title": f'{data["chengyu"]} ({data["pinyin"]})',
        "date": f"{date_str} {publish_time_utc}",
        "description": data["gloss"],
        "cover_image": cover_rel
    }
    if audio_mp3:
        fm["audio_url"] = audio_rel
        fm["audio_bytes"] = len(audio_mp3)

    post_md = _front_matter(fm) + body_md.strip() + "\n"

    if dry_run:
        print("DRY_RUN=True — not pushing. Would write:")
        print(" -", f"episodes/{folder}/cover.png")
        if audio_mp3: print(" -", f"episodes/{folder}/audio.mp3  ({len(audio_mp3)} bytes)")
        print(" -", f"episodes/{folder}/transcript.txt")
        print(" -", f"episodes/{folder}/metadata.json")
        print(" -", f"_posts/{date_str}-{slug}.md")
        return {"folder": folder, "post": f"{date_str}-{slug}.md"}

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")

    tmp = tempfile.mkdtemp(prefix="chengyu_pub_")
    try:
        repo_url = f"https://{token}@github.com/{repo}.git"
        run(["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmp], hide_token=True)
        run(["git", "config", "user.name", "Chengyu Publisher Bot"], cwd=tmp)
        run(["git", "config", "user.email", "actions@users.noreply.github.com"], cwd=tmp)

        # ✅ safety net: re-check duplicates **here**, after cloning
        existing = list_existing_chengyu(repo, branch)
        if normalize_chengyu(data["chengyu"]) in existing:
            raise RuntimeError(f"Duplicate idiom already published: {data['chengyu']}")

        # write episode assets
        dest_ep = Path(tmp)/"episodes"/folder
        dest_ep.mkdir(parents=True, exist_ok=True)
        (dest_ep/"cover.png").write_bytes(cover_png)
        (dest_ep/"transcript.txt").write_text(data["script"], encoding="utf-8")
        (dest_ep/"metadata.json").write_text(json.dumps({
            "show": show_name, **data, "pubDate": today.isoformat()
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if audio_mp3:
            (dest_ep/"audio.mp3").write_bytes(audio_mp3)

        # write post
        posts_dir = Path(tmp)/"_posts"
        posts_dir.mkdir(exist_ok=True)
        (posts_dir/f"{date_str}-{slug}.md").write_text(post_md, encoding="utf-8")

        # commit & push
        run(["git", "add", "."], cwd=tmp)
        run(["git", "commit", "-m", f"Add episode {folder}"], cwd=tmp)
        run(["git", "push", "origin", branch], cwd=tmp, hide_token=True)

        print("✔ Pushed one commit. Pages workflow will build & deploy.")
        return {"folder": folder, "post": f"{date_str}-{slug}.md"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
