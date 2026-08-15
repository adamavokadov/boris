#!/usr/bin/env bash
# Blocks a commit if it looks like it contains a Bitrix24 vibecode API key
# (or a couple of other common secret shapes) in plaintext.
#
# This is a blunt grep-based net, not a full secret scanner — it exists to
# catch the specific mistake that already happened once in this repo
# (a vibe_api_... key pasted directly into README.md), not to replace
# judgment. Rotate any key immediately if it's ever committed, regardless
# of whether this script catches it.
#
# --- Install as a git pre-commit hook (run once per local clone) ---
#   ln -sf ../../scripts/check-secrets.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# --- Run manually against staged changes at any time ---
#   ./scripts/check-secrets.sh
#
# --- Run manually against the whole working tree (not just staged) ---
#   ./scripts/check-secrets.sh --all

set -euo pipefail

# Patterns considered a leaked secret if found in plaintext.
PATTERNS=(
  'vibe_api_[A-Za-z0-9_]{10,}'   # Bitrix24 vibecode API key shape
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'  # PEM private keys
)

if [[ "${1:-}" == "--all" ]]; then
  # Scan the whole working tree (excluding .git and node_modules).
  TARGET_DESC="working tree"
  MATCHES=""
  for pattern in "${PATTERNS[@]}"; do
    found=$(grep -rEn --exclude-dir='.git' --exclude-dir='node_modules' -- "$pattern" . 2>/dev/null || true)
    if [[ -n "$found" ]]; then
      MATCHES="${MATCHES}${found}"$'\n'
    fi
  done
else
  # Default: only scan what's staged for this commit (the normal
  # pre-commit-hook use case) so the check is fast and only blocks what
  # you're about to actually push.
  TARGET_DESC="staged changes"
  MATCHES=""
  while IFS= read -r file; do
    [[ -f "$file" ]] || continue
    for pattern in "${PATTERNS[@]}"; do
      found=$(git diff --cached -- "$file" | grep -E "^\+" | grep -Ev '^\+\+\+' | grep -E -- "$pattern" || true)
      if [[ -n "$found" ]]; then
        MATCHES="${MATCHES}${file}: ${found}"$'\n'
      fi
    done
  done < <(git diff --cached --name-only --diff-filter=ACM)
fi

if [[ -n "$MATCHES" ]]; then
  echo "🔴 check-secrets.sh: possible secret found in ${TARGET_DESC}:" >&2
  echo "$MATCHES" >&2
  echo "" >&2
  echo "If this is a real key: do NOT commit it — remove it, use an env var" >&2
  echo "instead (see .env.example), and rotate the key if it was ever" >&2
  echo "committed anywhere before (even in a previous commit you amended)." >&2
  echo "If this is a false positive, adjust PATTERNS in scripts/check-secrets.sh." >&2
  exit 1
fi

echo "✅ check-secrets.sh: no known secret patterns found in ${TARGET_DESC}."
