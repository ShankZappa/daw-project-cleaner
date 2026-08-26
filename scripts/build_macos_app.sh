#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_bin=${PYTHON_BIN:-python3}
output_dir=${BUILD_OUTPUT_DIR:-"$project_dir/dist"}

if ! "$python_bin" -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "PyInstaller is required: python3 -m pip install pyinstaller" >&2
  exit 1
fi
if [ -e "$output_dir" ]; then
  echo "Refusing to overwrite existing $output_dir; move it aside first." >&2
  exit 1
fi

stage=$(mktemp -d "$project_dir/.build.XXXXXX")
cleanup_stage() {
  [ -n "${stage:-}" ] || return 0
  case "$stage" in
    "$project_dir"/.build.*) ;;
    *) echo "Refusing to clean unexpected build path: $stage" >&2; return 0 ;;
  esac
  [ ! -e "$stage" ] || find "$stage" -depth -delete
}
trap cleanup_stage EXIT
trap 'exit 1' HUP INT TERM
app_dir="$stage/DAW Project Cleaner.app"
contents="$app_dir/Contents"
macos="$contents/MacOS"
resources="$contents/Resources"
mkdir -p "$macos" "$resources/backend" "$stage/pyinstaller"

cd "$project_dir"
"$python_bin" -m PyInstaller --noconfirm --clean --onedir \
  --name "daw-project-cleaner-backend" \
  --distpath "$stage/pyinstaller-dist" \
  --workpath "$stage/pyinstaller" \
  --specpath "$stage" run_cli.py
cp -R "$stage/pyinstaller-dist/daw-project-cleaner-backend/." "$resources/backend/"
swiftc -target arm64-apple-macosx11.0 "$project_dir/native/App.swift" \
  -o "$macos/DAW Project Cleaner" -framework AppKit
cp "$project_dir/resources/Info.plist" "$contents/Info.plist"
cp "$project_dir/resources/support-qr.png" "$resources/support-qr.png"
cp "$project_dir/resources/AppIcon.icns" "$resources/AppIcon.icns"
codesign --force --deep --sign - "$app_dir"
mkdir "$output_dir"
mv "$app_dir" "$output_dir/DAW Project Cleaner.app"
echo "Built $output_dir/DAW Project Cleaner.app"
