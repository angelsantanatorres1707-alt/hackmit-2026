#!/usr/bin/env bash
# Store an API key and check it actually works.
#
#   bash scripts/setkey.sh
#
# Writes .env in the project root (gitignored, so it never reaches GitHub) and
# then makes a real call to confirm the key is valid. Finding out here beats
# finding out in front of judges.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
VENV="$REPO_ROOT/.venv"

echo
echo "  Set up handwriting reading"
echo "  ─────────────────────────────────────────────────"
echo
echo "  1) OpenAI       platform.openai.com/api-keys      (you said you have credits)"
echo "  2) Google       aistudio.google.com/apikey        (free, no credit card)"
echo "  3) Anthropic    console.anthropic.com/settings/keys"
echo
printf "  Which one? [1] "
read -r choice
choice="${choice:-1}"

case "$choice" in
  1) VAR="OPENAI_API_KEY";    NAME="OpenAI";    HINT="starts with sk-" ;;
  2) VAR="GEMINI_API_KEY";    NAME="Google";    HINT="starts with AIza" ;;
  3) VAR="ANTHROPIC_API_KEY"; NAME="Anthropic"; HINT="starts with sk-ant-" ;;
  *) echo "  Pick 1, 2 or 3."; exit 1 ;;
esac

echo
echo "  Paste your $NAME key ($HINT), then press Enter."
echo "  It will not appear as you type or paste. That is expected."
printf "  Key: "
# -s keeps the key off the screen and out of your terminal scrollback.
read -rs KEY
echo
echo

KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"

if [ -z "$KEY" ]; then
  echo "  Nothing pasted. Run it again."
  exit 1
fi

# Catch the classic paste mistakes before they become a confusing API error.
case "$KEY" in
  sk-*|AIza*) ;;
  *) echo "  That does not look like an API key ($HINT)."
     echo "  You may have copied the key's NAME from the dashboard rather than"
     echo "  the key itself. The real key is only shown once, when you create it."
     exit 1 ;;
esac

# Replace any existing line for this variable rather than appending a second one,
# since the later definition would silently win.
if [ -f "$ENV_FILE" ]; then
  grep -v "^${VAR}=" "$ENV_FILE" > "$ENV_FILE.tmp" 2>/dev/null || true
  mv "$ENV_FILE.tmp" "$ENV_FILE"
fi
printf '%s=%s\n' "$VAR" "$KEY" >> "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "  Saved to .env  (gitignored - this will not be committed)"
echo

if [ ! -x "$VENV/bin/python" ]; then
  echo "  No virtualenv yet. Run:  bash scripts/setup.sh"
  exit 1
fi

echo "  Checking the key against the real API..."
echo

set +e
( cd "$REPO_ROOT" && set -a && . "$ENV_FILE" && set +a \
  && "$VENV/bin/python" -m backend.vision_providers )
STATUS=$?
set -e

echo
if [ "$STATUS" -eq 0 ]; then
  cat <<'DONE'
  Working. Start the app with:

      bash scripts/run.sh --live

  It will read real photographs now. Without --live it uses the bundled
  samples, which still works with no key and no network.
DONE
else
  cat <<'FAILED'
  The check did not pass. Read the error above - it names the cause.

    "401" / "invalid api key"  the key is wrong or was revoked. Note the key
                              is shown ONCE, when created; the dashboard after
                              that lists only its name.
    "429"                     rate limited, or the account is out of credit.
    "could not reach"         a network problem, not a key problem. Check
                              wifi, a VPN, or a firewall blocking the API.

  Make a fresh key and run this again. In the meantime the app still works
  on the bundled samples:

      bash scripts/run.sh
FAILED
  exit 1
fi
