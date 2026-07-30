#!/bin/sh
set -eu
ROOT="$1"
printf 'sandbox-write\n' > "$ROOT/workspace-write.txt"
printf 'env_SECRET=%s\n' "${UNDECLARED_SECRET-ABSENT}"
if [ -e /etc/fieldbook-should-not-exist ]; then printf 'unexpected-host-file-visible\n'; exit 3; fi
if touch /etc/fieldbook-should-not-exist 2>/dev/null; then printf 'out-of-scope-write-succeeded\n'; exit 4; else printf 'out-of-scope-write-failed-closed\n'; fi
if /bin/sh -c 'command -v wget >/dev/null 2>&1 && wget -q -T 2 -O /dev/null https://example.com'; then printf 'network-available\n'; exit 5; else printf 'network-unavailable\n'; fi
