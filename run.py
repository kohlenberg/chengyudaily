# 1) create & activate a venv (once)
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 2) install deps
pip install -r requirements.txt

# 3) set secrets (in your shell or via a .env loader if you use one)
export OPENAI_API_KEY="sk-...yourkey..."
export GITHUB_TOKEN="ghp_...yourtoken..."

# 4a) run via package
python -m chengyu --dry-run        # no push, prints what it would do
python -m chengyu                  # generates + commits + pushes

# 4b) or via script
python scripts/make_episode.py --skip-tts
