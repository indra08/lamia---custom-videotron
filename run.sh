#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
    python_bin=.venv/bin/python
elif [ -x venv/bin/python ]; then
    python_bin=venv/bin/python
else
    printf '%s\n' 'Create a virtual environment and install requirements.txt first.' >&2
    exit 1
fi
exec "$python_bin" - <<'PY'
import os
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

load_dotenv(Path.cwd() / '.env')
uvicorn.run('app:app', host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '8000')))
PY
