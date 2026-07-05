#!/usr/bin/env bash
# Fateweaver web — builds the React app (first run) and serves it at
# http://127.0.0.1:8000 with the FastAPI backend. The GM still runs through
# the `claude` CLI with your existing login.
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8000}"

if ! command -v claude >/dev/null 2>&1; then
    echo "Note: the \`claude\` CLI was not found on PATH."
    echo "The Game Master needs Claude Code: https://claude.com/claude-code"
    echo
fi

if [ ! -d .venv ]; then
    echo "Creating .venv (one-time)..."
    "$PYTHON" -m venv .venv
fi
if ! .venv/bin/python -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "Installing server dependencies (fastapi, uvicorn)..."
    .venv/bin/python -m pip install --quiet fastapi "uvicorn[standard]"
fi

if [ ! -d web/dist ] || [ "${REBUILD:-}" = "1" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "npm not found — install Node.js to build the web app." >&2
        exit 1
    fi
    echo "Building the web app (one-time; REBUILD=1 to force)..."
    (cd web && npm install --no-fund --no-audit && npm run build)
fi

echo
echo "  ⚅ Fateweaver → http://127.0.0.1:$PORT"
echo
exec .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port "$PORT"
