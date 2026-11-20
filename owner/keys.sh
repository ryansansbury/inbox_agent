#!/bin/bash
# Saves one vendor's API key in the macOS Keychain as inbox-agent-<vendor>. Keys never go in a file.
#
#   bash owner/keys.sh anthropic --from SERVICE   copies a key another project already saved under SERVICE
#   bash owner/keys.sh anthropic                  after copying the key to the clipboard
#
# A typed Keychain prompt can cut a long key short, which is why a new key comes from the clipboard.
set -euo pipefail
vendor="${1:-}"
case "$vendor" in
  anthropic|openai) ;;
  *) echo "Usage: bash owner/keys.sh anthropic|openai [--from SERVICE]"; exit 1 ;;
esac
if [ "${2:-}" = "--from" ] && [ -n "${3:-}" ]; then
  key="$(security find-generic-password -s "$3" -w)"
else
  key="$(pbpaste)"
fi
if [ ${#key} -lt 20 ]; then
  echo "That doesn't look like a key. Copy it, or check the service name, and run this again."
  exit 1
fi
security add-generic-password -U -a "$USER" -s "inbox-agent-$vendor" -w "$key"
echo "Saved the $vendor key as inbox-agent-$vendor (${#key} characters)."
