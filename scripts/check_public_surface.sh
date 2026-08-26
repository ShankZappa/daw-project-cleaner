#!/bin/sh
# Refuse to publish private production data.
#
# The code was always meant to be public and the samples private, but nobody
# had checked the documents themselves. Before this guard existed, nine files
# intended for publication named real client projects, server share paths and
# the studio LAN address.
#
# Runs over every file Git would track. Exits non-zero on a hit.
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a Git repository; nothing to check." >&2
  exit 0
fi

# Client and production identifiers, server paths, studio network topology.
patterns='Annaliise|Anvelt|Siret Tuula|Telegramm|Kärt Anton|Janika Sillamaa|Kaarel Orumägi|Jessica Kari|Karolin Korre|Verbaarium|SINUTA|Salme|LKKK|Studio server|/Volumes/PROJECTS|/volume1|studio89-nas|studio89-ts|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}'

found=0
# -z/xargs -0 so paths with spaces survive.
git ls-files -z | while IFS= read -r -d '' file; do
  case "$file" in
    scripts/check_public_surface.sh) continue ;;
  esac
  if grep -nEI "$patterns" -- "$file" 2>/dev/null | grep -v 'Studio89 ' >/dev/null 2>&1; then
    echo "PRIVATE DATA in $file:"
    grep -nEI "$patterns" -- "$file" | grep -v 'Studio89 ' | head -5 | sed 's/^/    /'
    found=1
  fi
  echo "$found" > /tmp/.dpc_surface_found
done

if [ -f /tmp/.dpc_surface_found ] && [ "$(cat /tmp/.dpc_surface_found)" = "1" ]; then
  rm -f /tmp/.dpc_surface_found
  echo "" >&2
  echo "Refusing: tracked files contain private production data." >&2
  exit 1
fi
rm -f /tmp/.dpc_surface_found
echo "Public surface is clean: $(git ls-files | wc -l | tr -d ' ') tracked files checked."
