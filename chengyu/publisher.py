# chengyu/publisher.py
"""
Publish a new episode to the GitHub repo.

- Writes cover + transcript + metadata + _posts/ Markdown.
- Prefers repo-hosted MP3s (episodes/<date>-<slug>/audio.mp3).
- Optional: upload MP3 to GitHub Release instead.
- Light sanitizer + converts "Characters" tables to simple lines.
- Safe git clone (no interactive prompts, timeout).

Usage:
    publish_episode(
        show_name=...,
        repo="kohlenberg/chengyudaily",
        branch="main",
        site_url="https://kohlenberg.github.io/chengyudaily",
        baseurl="/chengyudaily",
        publish_time_utc="09:00:00",   # kept for compatibility
        data={ "chengyu": "...", "pinyin": "...", "gloss": "...", "teaser": "...", "script": "..." },
        body_md=body_md,               # already-structured episode Markdown
        cover_bytes=cover_img_bytes,
        cover_ext="jpg",               # or "png"
        audio_mp3=audio_bytes,         # or None
        upload_audio_to_release=False, # True => use Release asset URL
        write_audio_to_repo=True,      # True => write episodes/<folder>/audio.mp3
        dry_run=False,
    )
"""

import os
import re
import json
import yaml
import shutil
import tempfile
import subprocess
import datetime
from pathlib import Path
from unicodedata import normalize
from typing import Optional
import requests

# ----------------------- small utils -----------------------

def _slugify(text: str) -> str:
    txt = normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^\w\s-]", "", txt).strip().lower()
    txt = re.sub(r"[-\s]+", "-", txt)
    return txt or "episode"


def _run(cmd, cwd=None, quiet_token=False, timeout: Optional[int] = None, env: Optional[dict] = None):
    shown = " ".join(("***" if (quiet_token and "@" in str(x)) else str(x) for x in cmd))
    print("+", shown)
    subprocess.run(cmd, cwd=cwd, check=True, timeout=timeout, env=env)


def _git_clone(repo_url: str, branch: str, dest: str, timeout: int = 120):
    """Clone with no interactive prompts and sensible http timeouts."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "true"
    _run([
        "git",
        "-c", "http.lowSpeedLimit=1",
        "-c", "http.lowSpeedTime=30",
        "clone",
        "--filter=blob:none",
        "--depth", "1",
        "--branch", branch,
        repo_url, dest
    ], quiet_token=True, timeout=timeout, env=env)


def _gh_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        raise RuntimeError("GITHUB_TOKEN (or GH_TOKEN) not set")
    return tok


def _gh_headers():
    return {"Authorization": f"token {_gh_token()}", "Accept": "application/vnd.github+json"}


GITHUB_API = "https://api.github.com"

def _gh_create_or_get_release(repo: str, tag: str, name: str, body: str = "") -> dict:
    r = requests.post(f"{GITHUB_API}/repos/{repo}/releases",
                      headers=_gh_headers(),
                      json={"tag_name": tag, "name": name, "body": body,
                            "draft": False, "prerelease": False},
                      timeout=60)
    if r.status_code in (200, 201):
        return r.json()
    if r.status_code == 422 and "already_exists" in r.text:
        r2 = requests.get(f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}",
                          headers=_gh_headers(), timeout=30)
        r2.raise_for_status()
        return r2.json()
    raise RuntimeError(f"Create release failed: {r.status_code} {r.text}")


def _gh_upload_asset(upload_url_tmpl: str, filename: str, blob: bytes, content_type: str) -> dict:
    url = upload_url_tmpl.split("{")[0] + f"?name={filename}"
    h = _gh_headers()
    h["Content-Type"] = content_type
    r = requests.post(url, headers=h, data=blob, timeout=300)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Upload asset failed: {r.status_code} {r.text}")
    return r.json()

# ----------------------- body cleanup / characters lines -----------------------

def _sanitize_tables_min(md: str) -> str:
    """
    Light-touch sanitization:
    - Replace Unicode dashes (—, –) with '-' only on table-like lines.
    """
    out = []
    for ln in (md or "").splitlines():
        if ln.lstrip().startswith("|"):
            ln = ln.replace("—", "-").replace("–", "-")
        out.append(ln)
    return "\n".join(out)

def _characters_table_to_lines(md: str) -> str:
    """
    Convert a 'Characters' section that may contain a Markdown table (even broken)
    into simple lines:  字 (pinyin) — meaning
    Leaves other content intact.
    """
    # Find Characters section
    m = re.search(r"(?mis)(^|\n)#{1,6}\s*Characters\s*\n(?P<block>.*?)(?=\n#{1,6}\s|\Z)", md)
    if not m:
        return md

    block = m.group("block")

    # If it already looks like simple lines, bail out
    if re.search(r"^\s*[\u3400-\u9fff]+\s*\([^)]+\)\s*[—-]\s+.+$", block, flags=re.M):
        return md

    # Split glued rows (e.g., "| ... | | ... |")
    block = re.sub(r"\|\s+\|", "|\n|", block)

    # Extract table-like lines
    table_lines = [ln for ln in block.splitlines() if ln.strip().startswith("|")]
    rows = []
    if table_lines:
        for i, ln in enumerate(table_lines):
            raw = ln.strip().strip("|")
            cells = [c.strip() for c in raw.split("|")]
            # Skip header/separator
            if i == 0:
                continue
            if all(re.fullmatch(r"[-—–\s]+", c or "") for c in cells):
                continue
            if len(cells) >= 3:
                rows.append(cells[:3])

    # If still nothing, try parse from a single long line
    if not rows:
        one = block.replace("\n", " ")
        chunks = [g for g in re.split(r"\|\s*\|", one) if "|" in g]
        for ch in chunks:
            cells = [c.strip() for c in re.findall(r"\|\s*([^|]+?)\s*(?=\|)", ch)]
            if len(cells) >= 3:
                rows.append(cells[:3])

    if not rows:
        # Nothing to convert; return original
        return md

    lines = []
    for char, pinyin, meaning in rows:
        lines.append(f"{char} ({pinyin}) — {meaning}  ")

    # Rebuild the Characters section with simple lines
    heading_match = re.search(r"(?mi)^#{1,6}\s*Characters\s*$", md)
    heading = md[heading_match.start():heading_match.end()] if heading_match else "### Characters"
    simple_block = f"{heading}\n\n" + "\n".join(lines).rstrip() + "\n\n"

    return md[:m.start()] + simple_block + md[m.end():]

# ----------------------- main publisher -----------------------

def publish_episode(
    *,
    show_name: str,
    repo: str,
    branch: str,
    site_url: str,
    baseurl: str,
    publish_time_utc: str,     # kept for compatibility with earlier calls
    data: dict,                # {"chengyu","pinyin","gloss","teaser","script"}
    body_md: str,
    cover_bytes: bytes,
    cover_ext: str = "jpg",    # "jpg" | "png"
    audio_mp3: Optional[bytes] = None,
    upload_audio_to_release: bool = False,
    write_audio_to_repo: bool = True,   # prefer repo audio by default
    dry_run: bool = False,
    timeout_clone: int = 120,
):
    """
    Publish a new episode. Returns paths/URLs used.
    Prefer repo-hosted audio if write_audio_to_repo=True. If you set
    upload_audio_to_release=True and write_audio_to_repo=False we will use the
    Release asset URL instead.
    """
    cover_ext = (cover_ext or "jpg").lower()
    assert cover_ext in ("jpg", "jpeg", "png")

    # date + slug
    today = datetime.date.today()
    date_str = today.strftime("%Y-%m-%d")
    slug = _slugify(data.get("pinyin") or data.get("chengyu") or "episode")
    folder = f"{date_str}-{slug}"

    cover_name = f"cover.{'jpeg' if cover_ext in ('jpg','jpeg') else 'png'}"
    audio_repo_name = "audio.mp3"
    audio_release_name = f"{date_str}-{slug}.mp3"

    # Front matter — backdate 2 minutes to avoid "future" issues
    now_utc = datetime.datetime.utcnow() - datetime.timedelta(minutes=2)
    fm = {
        "layout": "post",
        "title": f"{data['chengyu']} ({data['pinyin']})",
        "date": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "description": data["gloss"],
        "cover_image": f"/episodes/{folder}/{cover_name}",
    }

    # If using Release-only audio, upload now to get URL
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

    # Prepare body: min sanitize + convert "Characters" to lines
    safe_body = _sanitize_tables_min(body_md or "")
    safe_body = _characters_table_to_lines(safe_body).strip()

    # clone, write, commit, push
    tmp = tempfile.mkdtemp(prefix="chengyu_pub_")
    try:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN not set")
        repo_url = f"https://{token}@github.com/{repo}.git"

        _git_clone(repo_url, branch, tmp, timeout=timeout_clone)
        _run(["git", "config", "user.name", "Chengyu Publisher Bot"], cwd=tmp)
        _run(["git", "config", "user.email", "actions@users.noreply.github.com"], cwd=tmp)

        ep_dir = Path(tmp) / "episodes" / folder
        ep_dir.mkdir(parents=True, exist_ok=True)

        # write cover, transcript, metadata
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

        # write post
        posts_dir = Path(tmp) / "_posts"
        posts_dir.mkdir(exist_ok=True)
        post_path = posts_dir / f"{date_str}-{slug}.md"
        front = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n"
        post_path.write_text(front + safe_body + "\n", encoding="utf-8")

        # commit & push
        _run(["git", "add", "."], cwd=tmp)
        _run(["git", "commit", "-m", f"Add episode {folder}"], cwd=tmp)
        if not dry_run:
            _run(["git", "push", "origin", branch], cwd=tmp, quiet_token=True)
            # Print canonical page URL (Jekyll permalink)
            y, m, d = date_str.split("-")
            base = (baseurl or "").rstrip("/")
            page_url = f"{site_url.rstrip('/')}{base}/{y}/{m}/{d}/{slug}.html"
            print("✔ Pushed. Pages will rebuild.")
            print("Episode page:", page_url)
        else:
            print("DRY_RUN=True — not pushed.")

        return {
            "folder": folder,
            "post": str(post_path),
            "cover": str(ep_dir / cover_name),
            "audio_repo_path": str(ep_dir / audio_repo_name) if (audio_mp3 and write_audio_to_repo) else None,
            "release_asset_url": release_asset_url,
        }

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
