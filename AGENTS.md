# Repository Guidelines

## Project Structure & Module Organization

This is Vistara, a local videotron advertising MVP built with FastAPI, SQLite, and vanilla HTML/CSS/JavaScript.

- `app.py` contains API routes, database initialization, authentication, booking, pricing, moderation, and simulated payments.
- `static/index.html`, `static/app.js`, and `static/style.css` provide the Indonesian single-page interface.
- `tests/test_pricing.py` contains pricing regression tests.
- `uploads/` stores runtime assets; `videotron.db` stores local application data.
- `requirements.txt` lists runtime and test dependencies; `README.md` documents setup and demo limitations.

## Build, Test, and Development Commands

Use Python 3.10 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app:app --reload
python -m pytest tests/
```

The server runs at `http://127.0.0.1:8000`; interactive API documentation is at `/docs`. Static assets are served directly, with no frontend build step. Use `app:app` as the entry point: the commands currently in `run.sh` reference incompatible module paths.

## Coding Style & Naming Conventions

Use four-space indentation for Python, `snake_case` for functions and variables, and uppercase names for configuration constants. JavaScript uses `camelCase`; CSS uses descriptive class names. Follow surrounding conventions and avoid unrelated reformatting of the compact existing files. No formatter or linter configuration is currently included.

Preserve timezone-aware timestamps, `Asia/Jakarta` pricing boundaries, and Decimal calculations with per-day `ROUND_HALF_UP` rounding.

## Testing Guidelines

Use pytest, naming files `test_*.py` and functions `test_*`. Existing tests cover partial-day pricing and month boundaries; no coverage threshold is configured. Add regression cases for changed pricing or booking behavior. For database tests, set `DB_PATH` to a temporary database before importing `app`, which initializes storage on import. Manually verify affected booking, admin, or player flows; include screenshots for interface changes.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout. Use concise, imperative commit subjects such as `Fix month-boundary pricing`. Keep changes focused. Pull requests should describe behavior changes, link relevant issues, list validation commands and results, and identify schema or configuration impacts.

## Security & Configuration

Set `APP_SECRET`, `ADMIN_PASSWORD`, and `DEVICE_TOKEN` locally. Keep secrets, virtual environments, databases, and uploaded customer content out of commits. Keep this demo restricted to localhost; OTP and payment flows are simulations, and content requires manual approval.
