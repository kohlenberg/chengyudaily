# chengyu/publisher.py
# Publishes an episode to your GitHub repo (Pages) and optionally creates
# a GitHub Release with the MP3 as an asset.
#
# Writes in repo:
#   episodes/<date>-<slug>/{cover.(jpg|png), transcript.txt, metadata.json, audio.mp3?}
#   _posts/<date>-<slug>.md  (front matter includes cover_image and audio_url)
#
# Optional:
#   - upload_audio_to_release=True  -> creates a Release and uploads MP3 asset
#   - write_audio_to_repo=False     -> skip committing audio file if you only want Releases

import os, re, json, tempfile, shutil, subprocess, datetime
from pathlib import Path
from unicodedata import normalize

import yaml
import requests

# ---------------- git helpers ----------------

def _run(cmd, cwd=None, quiet_token: bool = False):
    shown = " ".join(("***" if (quiet_token and "@" in str(x)) else str(x) for x in cmd))
    print("+", shown)
    subprocess.check_call(cmd, cwd=cwd)

def _slugify(text: str) -> str:
    txt = normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^\w\s-]", "", txt, flags=re.U).strip().lower()
    txt = re.sub(r"[-\s]+", "-", txt, flags=re.U)
    return txt or "episode"

# ---------------- GitHub API (Releases) ----------------

GITHUB_API = "https://api.github.com"

def _gh_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        raise RuntimeError("GITHUB_TOKEN (or GH_TOKEN) not set")
    return tok

def _gh_headers():
    return {
        "Authorization": f"token {_gh_token()}",
        "Accept": "application/vnd.github+json",
    }

def _gh_create_or_get_release(repo: str, tag: str, name: str, body: str = "") -> dict:
    url = f"{GITHUB_API}/repos/{repo}/releases"
    payload = {"tag_name": tag, "name": name, "body": body, "draft": False, "prerelease": False}
    r = requests.post(url, headers=_gh_headers(), json=payload, timeout=60)
    if r.status_code in (200, 201):
        return r.json()
    # If tag exists, fetch it
    if r.status_code == 422 and "already_exists" in r.text:
        r2 = requests.get(f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}", headers=_gh_headers(), timeout=60)
        r2.raise_for_status()
        return r2.json()
    raise RuntimeError(f"Create release failed: {r.status_code} {r.text}")

def _gh_upload_asset(upload_url_template: str, filename: str, blob: bytes, content_type: str) -> dict:
    upload_url = upload_url_template.split("{")[0] + f"?name={filename}"
    headers = _gh_headers()
    headers["Content-Type"] = content_type
    r = requests.post(upload_url, headers=headers, data=blob, timeout=300)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Upload asset failed: {r.status_code} {r.text}")
    return r.json()

# ---------------- main publish API ----------------

def publish_episode(
    *,
    show_name: str,
    repo: str,                 # e.g. "kohlenberg/chengyudaily"
    branch: str,               # "main"
    site_url: str,             # e.g. "https://kohlenberg.github.io/chengyudaily"
    baseurl: str,              # e.g. "/chengyudaily"
    publish_time_utc: str,     # "09:00:00" (kept for compatibility; see date override below)
    data: dict,                # {"chengyu","pinyin","gloss","teaser","script"}
    body_md: str,              # structured markdown for the post
    cover_bytes: bytes,        # cover image bytes
    cover_ext: str = "jpg",    # "jpg" or "png"
    audio_mp3: bytes | None = None,
    upload_audio_to_release: bool = False,  # << enable GitHub Release upload
    write_audio_to_repo: bool = True,       # << also commit audio file into repo
    dry_run: bool = False,
):
    """
    Returns: dict with keys {folder, post_path, cover_path, audio_repo_path?, release_asset_url?}
    """
    cover_ext = cover_ext.lower()
    assert cover_ext in ("jpg", "jpeg", "png"), "cover_ext must be jpg|png"

    # Date & slug
    today = datetime.date.today()
    date_str = today.strftime("%Y-%m-%d")
    slug = _slugify(data["pinyin"])
    folder = f"{date_str}-{slug}"

    # Filenames
    cover_name = f"cover.{'jpeg' if cover_ext in ('jpg','jpeg') else 'png'}"
    audio_name = f"{date_str}-{slug}.mp3"  # nice, stable asset name for Releases

    # Front matter (stamp current UTC - 2 minutes to avoid "future post" hiding)
    now_utc = datetime.datetime.utcnow() - datetime.timedelta(minutes=2)
    fm = {
        "layout": "post",
        "title": f"{data['chengyu']} ({data['pinyin']})",
        "date": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "description": data["gloss"],
        "cover_image": f"/episodes/{folder}/{cover_name}",
    }

    # If we want a Release URL, create the release *first* so we have the asset URL for front matter
    release_asset_url = None
    if upload_audio_to_release and audio_mp3:
        tag  = f"v{date_str.replace('-','')}-{slug}"
        name = f"{data['chengyu']} ({data['pinyin']})"
        body = f"Episode: {data['chengyu']}"
        rel  = _gh_create_or_get_release(repo, tag=tag, name=name, body=body)
        asset = _gh_upload_asset(rel["upload_url"], filename=audio_name, blob=audio_mp3, content_type="audio/mpeg")
        release_asset_url = asset.get("browser_download_url")
        fm["audio_url"] = release_asset_url
        fm["audio_bytes"] = len(audio_mp3)

    # Clone → write → commit → push
    tmp = tempfile.mkdtemp(prefix="chengyu_pub_")
    try:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN not set")

        repo_url = f"https://{token}@github.com/{repo}.git"
        _run(["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmp], quiet_token=True)
        _run(["git", "config", "user.name", "Chengyu Publisher Bot"], cwd=tmp)
        _run(["git", "config", "user.email", "actions@users.noreply.github.com"], cwd=tmp)

        # Episode assets
        ep_dir = Path(tmp) / "episodes" / folder
        ep_dir.mkdir(parents=True, exist_ok=True)

        cover_path = ep_dir / cover_name
        cover_path.write_bytes(cover_bytes)

        (ep_dir / "transcript.txt").write_text(data["script"], encoding="utf-8")
        (ep_dir / "metadata.json").write_text(json.dumps({
            "show": show_name,
            "chengyu": data["chengyu"],
            "pinyin": data["pinyin"],
            "gloss": data["gloss"],
            "teaser": data["teaser"],
            "script": data["script"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        # Audio file in repo (optional if you're using Releases-only)
        audio_repo_path = None
        if audio_mp3 and write_audio_to_repo:
            audio_repo_path = ep_dir / "audio.mp3"
            audio_repo_path.write_bytes(audio_mp3)
            # If we didn't upload to Releases, point front matter to the repo file
            if not upload_audio_to_release:
                fm["audio_url"] = f"/episodes/{folder}/audio.mp3"
                fm["audio_bytes"] = len(audio_mp3)

        # Post markdown
        posts_dir = Path(tmp) / "_posts"
        posts_dir.mkdir(exist_ok=True)
        post_path = posts_dir / f"{date_str}-{slug}.md"
        front = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n"
        post_path.write_text(front + (str if isinstance(json, str) else lambda x: x)(data["script"]) and "" + front or "")

        # Wait, ^ that line is wrong—write the real body passed in:
        post_path.write_text(front + ("" if body_md is None else body_md.strip()) + "\n", encoding="utf-8")

        # Commit & push
        _run(["git", "add", "."], cwd=tmp)
        _run(["git", "commit", "-m", f"Add episode {folder}"], cwd=tmp)
        if not dry_run:
            _run(["git", "push", "origin", branch], cwd=tmp, quiet_token=True)
            print("✔ Pushed. Pages will rebuild shortly.")
            print(f"Episode page (after deploy): {site_url}/{date_str}-{slug}.html")
        else:
            print("DRY_RUN=True — changes staged locally only.")

        return {
            "folder": folder,
            "post_path": str(post_path),
            "cover_path": str(cover_path),
            "audio_repo_path": str(audio_repo_path) if audio_repo_path else None,
            "release_asset_url": release_asset_url,
        }

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
