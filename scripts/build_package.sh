#!/bin/sh
# Build the distributable Python package.
#
# This is what outside users receive: the application bundle is ad-hoc signed
# and cannot be handed to anyone else. See docs/MASS_USE_READINESS.md §1.
#
#   scripts/build_package.sh           normal build
#   scripts/build_package.sh --beta    permanent deletion compiled out
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_bin=${PYTHON_BIN:-python3}
beta=0
[ "${1:-}" = "--beta" ] && beta=1

cd "$project_dir"
sh scripts/check_public_surface.sh
"$python_bin" -m unittest discover >/dev/null
echo "Tests pass; public surface clean."

init="daw_project_cleaner/__init__.py"
proj="pyproject.toml"
restore_sources() {
  [ -f "$init.orig" ] && mv "$init.orig" "$init"
  [ -f "$proj.orig" ] && mv "$proj.orig" "$proj"
  return 0
}
trap restore_sources EXIT INT TERM HUP

if [ "$beta" = "1" ]; then
  base=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$init")
  [ -n "$base" ] || { echo "Could not read the version" >&2; exit 1; }
  cp "$init" "$init.orig"
  cp "$proj" "$proj.orig"
  # Absent, not merely gated.
  sed -i '' 's/^PURGE_ENABLED = True$/PURGE_ENABLED = False/' "$init"
  # A beta must be identifiable from the filename and from --version, or it
  # cannot be told apart from the build that can delete.
  sed -i '' "s/^__version__ = \"$base\"\$/__version__ = \"${base}b1\"/" "$init"
  sed -i '' "s/^version = \"$base\"\$/version = \"${base}b1\"/" "$proj"
  grep -q '^PURGE_ENABLED = False$' "$init" || { echo "Could not disable purge" >&2; exit 1; }
  echo "Beta build ${base}b1: permanent deletion is compiled out."
fi

rm -rf dist-package
"$python_bin" -m build --outdir dist-package . >/dev/null
restore_sources
trap - EXIT INT TERM HUP

echo ""
for f in dist-package/*; do
  echo "  $(basename "$f")  $(wc -c < "$f" | tr -d ' ') bytes"
done
if tar tzf dist-package/*.tar.gz | grep -qE 'internal-research|work-reports|releases/'; then
  echo "REFUSING: private material in the sdist" >&2
  exit 1
fi
echo ""
echo "Verify before publishing: install the wheel into a clean virtual"
echo "environment and run one scan -> quarantine -> restore cycle."
