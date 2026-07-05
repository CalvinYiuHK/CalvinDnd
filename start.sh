#!/usr/bin/env bash
# Entry point for Fateweaver.
# Launches the clickable TUI (installing `textual` into .venv on first run);
# falls back to the classic zero-dependency prompt game if that fails.
# The Game Master runs through the `claude` CLI using your existing login.
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v claude >/dev/null 2>&1; then
    echo "Note: the \`claude\` CLI was not found on PATH."
    echo "The Game Master needs Claude Code: https://claude.com/claude-code"
    echo
fi

if [ "${1:-}" = "--classic" ]; then
    exec "$PYTHON" game.py
fi

if [ ! -d .venv ]; then
    echo "Setting up the TUI (one-time)..."
    "$PYTHON" -m venv .venv >/dev/null 2>&1 || true
fi
if [ -x .venv/bin/python ]; then
    if ! .venv/bin/python -c "import textual" >/dev/null 2>&1; then
        echo "Installing textual..."
        .venv/bin/python -m pip install --quiet textual || true
    fi
    if .venv/bin/python -c "import textual" >/dev/null 2>&1; then
        exec .venv/bin/python tui.py
    fi
fi

echo "(TUI unavailable — starting classic mode. Run ./start.sh --classic to skip the check.)"
exec "$PYTHON" game.py
