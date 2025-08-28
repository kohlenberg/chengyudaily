# chengyu/publisher.py

import os, re, json, tempfile, shutil, subprocess, datetime
from pathlib import Path
from unicodedata import normalize
import yaml, requests

def _run(cmd, cwd=None, quiet_token=False):
    shown = " ".join(("***" if (quiet_token and "@" in str(x)) else str(x) for x in cmd))
    print("+", shown)
    subprocess.check_call(cmd, cwd=cwd)

def _slugify(text: str) -> str:
    txt = normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^\w\s-]", "", txt).strip().lower()
    txt = re.sub(r"[-\s]+", "-", txt)
    return txt or "episode"

# --- GitHub release helpers (only used if you enable upload_audio_to_release) ---
GITHUB_API = "https://api.github.com"
def _gh_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok: raise RuntimeError("GITHUB_TOKEN (or GH_TOKEN) not set")
    return tok
def _gh_headers():
    return {"Authorization": f"token {_gh_token()}", "Accept": "application/vnd.github+json"}
def _gh_create_or_get_release(repo: str, tag: str, name: str, body: str = "") -> dict:
    r = requests.post(f"{GITHUB_API}/repos/{repo}/releases",
                      headers=_gh_headers(),
                      json={"tag_name": tag, "name": name, "body": body, "draft": False, "prerelease": False},
                      timeout=60)
    if r.status_code in (200,201): return r.json()
    if r.status_code == 422 and "already_exists" in r.text:
        r2 = requests.get(f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}",
                          headers=_gh_headers(), timeout=60)
        r2.raise_for_status(); return r2.json()
    raise RuntimeError(f"Create release failed: {r.status_code} {r.text}")
def _gh_upload_asset(upload_url_tmpl: str, filename: str, blob: bytes, content_type: str) -> dict:
    url = upload_url_tmpl.split("{")[0] + f"?name={filename}"
    h = _gh_headers(); h["Content-Type"] = content_type
    r = requests.post(url, headers=h, data=blob, timeout=300)
    if r.status_code not in (200,201):
        raise RuntimeError(f"Upload asset failed: {r.status_code} {r.text}")
    return r.json()

def publish_episode(
    *,
    show_name: str,
    repo: str,
    branch: str,
    site_url: str,
    baseurl: str,
    publish_time_utc: str,     # kept for compatibility
    data: dict,                # {"chengyu","pinyin","gloss","teaser","script"}
    body_md: str,
    cover_bytes: bytes,
    cover_ext: str = "jpg",    # "jpg" | "png"
    audio_mp3: bytes | None = None,
    upload_audio_to_release: bool = False,
    write_audio_to_repo: bool = True,
    dry_run: bool = False,
):
    cover_ext = cover_ext.lower()
    assert cover_ext in ("jpg","jpeg","png")

    # date/slug
    today = datetime.date.today()
    date_str = today.strftime("%Y-%m-%d")
    slug = _slugify(data["pinyin"])
    folder = f"{date_str}-{slug}"

    cover_name = f"cover.{'jpeg' if cover_ext in ('jpg','jpeg') else 'png'}"
    audio_repo_name = "audio.mp3"
    audio_release_name = f"{date_str}-{slug}.mp3"  # nice stable asset name

    # front matter (stamp now-2min to avoid "future")
    now_utc = datetime.datetime.utcnow() - datetime.timedelta(minutes=2)
    fm = {
        "layout": "post",
        "title": f"{data['chengyu']} ({data['pinyin']})",
        "date": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "description": data["gloss"],
        "cover_image": f"/episodes/{folder}/{cover_name}",
    }

    # If we plan to use Releases (and NOT write to repo), prep release first
    release_asset_url = None
    if audio_mp3 and upload_audio_to_release and not write_audio_to_repo:
        tag = f"v{date_str.replace('-','')}-{slug}"
        rel = _gh_create_or_get_release(repo, tag=tag,
                                        name=f"{data['chengyu']} ({data['pinyin']})",
                                        body=f"Episode: {data['chengyu']}")
        asset = _gh_upload_asset(rel["upload_url"], filename=audio_release_name,
                                 blob=audio_mp3, content_type="audio/mpeg")
        release_asset_url = asset.get("browser_download_url")
        fm["audio_url"] = release_asset_url
        fm["audio_bytes"] = len(audio_mp3)

    # git clone → write → commit → push
    tmp = tempfile.mkdtemp(prefix="chengyu_pub_")
    try:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token: raise RuntimeError("GITHUB_TOKEN not set")
        repo_url = f"https://{token}@github.com/{repo}.git"

        _run(["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmp], quiet_token=True)
        _run(["git", "config", "user.name", "Chengyu Publisher Bot"], cwd=tmp)
        _run(["git", "config", "user.email", "actions@users.noreply.github.com"], cwd=tmp)

        ep_dir = Path(tmp) / "episodes" / folder
        ep_dir.mkdir(parents=True, exist_ok=True)

        # write cover & metadata
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

        # prefer repo audio if requested
        if audio_mp3 and write_audio_to_repo:
            (ep_dir / audio_repo_name).write_bytes(audio_mp3)
            fm["audio_url"] = f"/episodes/{folder}/{audio_repo_name}"
            fm["audio_bytes"] = len(audio_mp3)

        # post markdown
        posts_dir = Path(tmp) / "_posts"
        posts_dir.mkdir(exist_ok=True)
        post_path = posts_dir / f"{date_str}-{slug}.md"
        front = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n"
        post_path.write_text(front + (body_md or "").strip() + "\n", encoding="utf-8")

        # commit & push
        _run(["git", "add", "."], cwd=tmp)
        _run(["git", "commit", "-m", f"Add episode {folder}"], cwd=tmp)
        if not dry_run:
            _run(["git", "push", "origin", branch], cwd=tmp, quiet_token=True)
            print("✔ Pushed. Pages will rebuild.")
            print(f"Episode page: {site_url}/{date_str}-{slug}.html")
        else:
            print("DRY_RUN=True — not pushed.")

        return {
            "folder": folder,
            "post_path": str(post_path),
            "cover_path": str((ep_dir / cover_name)),
            "audio_repo_path": str((ep_dir / audio_repo_name)) if (audio_mp3 and write_audio_to_repo) else None,
            "release_asset_url": release_asset_url,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
