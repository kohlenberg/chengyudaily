import os, json, tempfile, shutil
from pathlib import Path
from .utils import run, normalize_chengyu

def list_existing_chengyu(repo: str, branch: str = "main") -> set[str]:
    """Clone shallowly and gather ALL published chengyu (normalized)."""
    token = os.environ.get("GITHUB_TOKEN")
    tmp = tempfile.mkdtemp(prefix="chengyu_seen_")
    seen = set()
    try:
        repo_url = f"https://{token+'@' if token else ''}github.com/{repo}.git"
        run(["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmp], hide_token=bool(token))
        root = Path(tmp)

        for meta in (root / "episodes").glob("*/metadata.json"):
            try:
                d = json.loads(meta.read_text(encoding="utf-8"))
                if d.get("chengyu"):
                    seen.add(normalize_chengyu(d["chengyu"]))
            except Exception:
                pass

        for post in (root / "_posts").glob("*.md"):
            try:
                txt = post.read_text(encoding="utf-8")
                if txt.startswith("---"):
                    end = txt.find("\n---", 3)
                    fm = txt[4:end] if end != -1 else ""
                    for line in fm.splitlines():
                        if line.strip().startswith("title:"):
                            title = line.split(":",1)[1].strip().strip('"').strip("'")
                            ch = title.split("(")[0].strip()
                            if ch:
                                seen.add(normalize_chengyu(ch))
            except Exception:
                pass
        return seen
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
