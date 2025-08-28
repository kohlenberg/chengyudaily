# chengyu/publisher.py
# Publishes a generated episode to your GitHub repo (Pages).
# - writes: episodes/<date>-<slug>/{cover.(jpg|png), transcript.txt, metadata.json, audio.mp3?}
# - writes: _posts/<date>-<slug>.md with correct cover_image + (optional) audio_url

import os, re, json, tempfile, shutil, subprocess, datetime
from pathlib import Path
from unicodedata import normalize
import yaml

def _run(cmd, cwd=None, quiet_token: bool = False):
    shown = " ".join(("***" if (quiet_token and "@" in str(x)) else str(x) for x in cmd))
    print("+", shown)
    subprocess.check_call(cmd, cwd=cwd)

def _slugify(text: str) -> str:
    txt = normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^\w\s-]", "", txt, flags=re.U).strip().lower()
    txt = re.sub(r"[-\s]+", "-", txt, flags=re.U)
    return txt or "episode"

def publish_episode(
    *,
    show_name: str,
    repo: str,                 # e.g. "kohlenberg/chengyudaily"
    branch: str,               # "main"
    site_url: str,             # e.g. "https://kohlenberg.github.io/chengyudaily"
    baseurl: str,              # e.g. "/chengyudaily"
    publish_time_utc: str,     # "09:00:00"
    data: dict,                # {"chengyu","pinyin","gloss","teaser","script"}
    body_md: str,              # structured markdown for the post
    cover_bytes: bytes,        # << cover image bytes
    cover_ext: str = "jpg",    # << "jpg" or "png"
    audio_mp3: bytes | None = None,
    dry_run: bool = False,
):
    cover_ext = cover_ext.lower()
    assert cover_ext in ("jpg", "jpeg", "png"), "cover_ext must be jpg|png"

    today = datetime.date.today()
    date_str = today.strftime("%Y-%m-%d")

    slug = _slugify(data["pinyin"])
    folder = f"{date_str}-{slug}"

    cover_name = f"cover.{'jpeg' if cover_ext in ('jpg','jpeg') else 'png'}"
    audio_name = "audio.mp3"

    # front matter
    fm = {
        "layout": "post",
        "title": f"{data['chengyu']} ({data['pinyin']})",
        "date": f"{date_str} {publish_time_utc}",
        "description": data["gloss"],
        "cover_image": f"/episodes/{folder}/{cover_name}",
    }

    tmp = tempfile.mkdtemp(prefix="chengyu_pub_")
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN not set")

        repo_url = f"https://{token}@github.com/{repo}.git"
        _run(["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmp], quiet_token=True)
        _run(["git", "config", "user.name", "Chengyu Publisher Bot"], cwd=tmp)
        _run(["git", "config", "user.email", "actions@users.noreply.github.com"], cwd=tmp)

        # episode assets
        ep_dir = Path(tmp) / "episodes" / folder
        ep_dir.mkdir(parents=True, exist_ok=True)

        (ep_dir / cover_name).write_bytes(cover_bytes)
        (ep_dir / "transcript.txt").write_text(data["script"], encoding="utf-8")
        (ep_dir / "metadata.json").write_text(json.dumps({
            "show": show_name,
            "chengyu": data["chengyu"],
            "pinyin": data["pinyin"],
            "gloss": data["gloss"],
            "teaser": data["teaser"],
            "script": data["script"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        if audio_mp3:
            (ep_dir / audio_name).write_bytes(audio_mp3)
            fm["audio_url"] = f"/episodes/{folder}/{audio_name}"
            fm["audio_bytes"] = len(audio_mp3)

        # post
        posts_dir = Path(tmp) / "_posts"
        posts_dir.mkdir(exist_ok=True)
        post_path = posts_dir / f"{date_str}-{slug}.md"
        front = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n"
        post_path.write_text(front + body_md.strip() + "\n", encoding="utf-8")

        # commit + push
        _run(["git", "add", "."], cwd=tmp)
        _run(["git", "commit", "-m", f"Add episode {folder}"], cwd=tmp)
        if not dry_run:
            _run(["git", "push", "origin", branch], cwd=tmp, quiet_token=True)
            print("✔ Pushed. Pages will rebuild shortly.")
            print(f"Episode page (after deploy): {site_url}/{date_str}-{slug}.html")
        else:
            print("DRY_RUN=True — changes staged locally only.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
