#!/bin/bash
# Install the sandbox runtime as root-owned files before enabling the unit.
set -Eeuo pipefail
(( EUID == 0 )) || { printf 'must run as root\n' >&2; exit 1; }
readonly SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly TARGET_DIR=/usr/local/libexec
# Never replace the only recovery runtime underneath an active deployment.
# An operator must stop/migrate it explicitly and then rerun this installer.
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet fieldbook-sandbox.service; then
  state=/var/lib/fieldbook-sandbox/runtime-state.conf
  if [[ ! -f "$state" ]] || ! grep -qx 'version=3' "$state"; then
    printf 'refusing upgrade: fieldbook-sandbox.service is active with missing or legacy state; stop the service and perform the documented migration before replacing runtime scripts\n' >&2
  else
    printf 'refusing upgrade: fieldbook-sandbox.service is active; stop the service and verify teardown before replacing runtime scripts\n' >&2
  fi
  exit 1
fi
install -d -o root -g root -m 0755 "$TARGET_DIR"
for name in setup teardown; do
  install -o root -g root -m 0755 \
    "$SOURCE_DIR/fieldbook-sandbox-${name}.sh" \
    "$TARGET_DIR/fieldbook-sandbox-${name}"
done
for name in setup teardown; do
  path="$TARGET_DIR/fieldbook-sandbox-${name}"
  [[ "$(stat -c '%u:%g:%a' "$path")" == "0:0:755" ]] || {
    printf 'untrusted installed runtime: %s\n' "$path" >&2
    exit 1
  }
done
printf 'Installed root-owned Fieldbook sandbox runtimes in %s\n' "$TARGET_DIR"
