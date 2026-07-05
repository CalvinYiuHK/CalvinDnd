#!/usr/bin/env bash
# Fateweaver web — serves the React app at http://127.0.0.1:8000 with the
# FastAPI backend. The GM still runs through the `claude` CLI.
#
# The built frontend ships in web/dist, so Node/npm are NOT needed to play.
# REBUILD=1 ./start-web.sh rebuilds the frontend (needs a modern npm).
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

# Find an npm that actually works with the installed node (conda and old
# global installs often shadow a broken npm 6 that crashes on modern node).
find_npm() {
    local IFS=:
    for dir in $PATH; do
        [ -x "$dir/npm" ] || continue
        local v major
        v=$("$dir/npm" --version 2>/dev/null) || continue
        major=${v%%.*}
        if [ "${major:-0}" -ge 8 ] 2>/dev/null; then
            echo "$dir/npm"
            return 0
        fi
    done
    return 1
}

if [ ! -d web/dist ] || [ "${REBUILD:-}" = "1" ]; then
    NPM=$(find_npm) || {
        echo "No working npm (>= 8) found on PATH — cannot build the frontend." >&2
        echo "Install a current Node.js (https://nodejs.org) or, if you use" >&2
        echo "conda, its base env may shadow a broken npm 6: try 'conda deactivate'." >&2
        exit 1
    }
    echo "Building the web app with $NPM ($($NPM --version))..."
    (cd web && "$NPM" install --no-fund --no-audit && "$NPM" run build)
fi

echo
echo "  ⚅ Fateweaver → http://127.0.0.1:$PORT"
echo
exec .venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port "$PORT"
