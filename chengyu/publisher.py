from .dedupe import list_existing_chengyu
from .utils import normalize_chengyu

# ... after clone:
existing = list_existing_chengyu(repo, branch)
if normalize_chengyu(data["chengyu"]) in existing:
    raise RuntimeError(f"Duplicate idiom already published: {data['chengyu']}")
