#!/usr/bin/env bash
# Entry point for Old Greg's Tavern.
# The game is pure-stdlib Python; the Game Master runs through the `claude`
# CLI (Claude Code) using your existing login — no API key, no pip installs.
set -e

cd "$(dirname "$0")"

if ! command -v claude >/dev/null 2>&1; then
    echo "Note: the \`claude\` CLI was not found on PATH."
    echo "The Game Master needs Claude Code: https://claude.com/claude-code"
    echo "(Character creation and dice still work without it.)"
    echo
fi

exec "${PYTHON:-python3}" game.py
