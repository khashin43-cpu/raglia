#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${LIA_OFFICECLI_INSTALL_DIR:-$SCRIPT_DIR/bin}"
REPOSITORY="iOfficeAI/OfficeCLI"
MIRROR_BASE="https://d.officecli.ai"
GITHUB_BASE="https://github.com/$REPOSITORY"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lia-officecli.XXXXXX")"
trap 'rm -rf -- "$TEMP_DIR"' EXIT

os_name="$(uname -s | tr '[:upper:]' '[:lower:]')"
architecture="$(uname -m)"

case "$os_name/$architecture" in
  darwin/arm64) asset="officecli-mac-arm64" ;;
  darwin/x86_64) asset="officecli-mac-x64" ;;
  linux/x86_64) asset="officecli-linux-x64" ;;
  linux/aarch64 | linux/arm64) asset="officecli-linux-arm64" ;;
  *)
    echo "Unsupported OfficeCLI platform: $os_name/$architecture" >&2
    exit 1
    ;;
esac

resolve_latest_version() {
  local effective_url
  effective_url="$(curl -fsSL --max-time 30 -o /dev/null -w '%{url_effective}' "$MIRROR_BASE/releases/latest" 2>/dev/null || true)"
  if [[ "$effective_url" == */releases/tag/v* ]]; then
    echo "${effective_url##*/tag/}"
    return
  fi
  effective_url="$(curl -fsSL --max-time 30 -o /dev/null -w '%{url_effective}' "$GITHUB_BASE/releases/latest")"
  echo "${effective_url##*/tag/}"
}

download_with_fallback() {
  local path="$1"
  local output="$2"
  if curl -fsSL --connect-timeout 5 --max-time 300 "$MIRROR_BASE/$path" -o "$output"; then
    return
  fi
  curl -fsSL --max-time 300 "$GITHUB_BASE/$path" -o "$output"
}

version="$(resolve_latest_version)"
if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Unable to resolve the latest OfficeCLI version" >&2
  exit 1
fi

release_path="releases/download/$version"
binary_path="$TEMP_DIR/officecli"
checksum_path="$TEMP_DIR/SHA256SUMS"

echo "Downloading OfficeCLI $version ($asset)..."
download_with_fallback "$release_path/$asset" "$binary_path"
download_with_fallback "$release_path/SHA256SUMS" "$checksum_path"

expected_checksum="$(awk -v name="$asset" '$2 == name {print $1; exit}' "$checksum_path")"
if [[ -z "$expected_checksum" ]]; then
  echo "OfficeCLI checksum for $asset was not found" >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  actual_checksum="$(sha256sum "$binary_path" | awk '{print $1}')"
else
  actual_checksum="$(shasum -a 256 "$binary_path" | awk '{print $1}')"
fi

if [[ "$expected_checksum" != "$actual_checksum" ]]; then
  echo "OfficeCLI checksum mismatch" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR"
install_path="$INSTALL_DIR/officecli"
cp "$binary_path" "$install_path.new"
chmod 0755 "$install_path.new"

if [[ "$os_name" == "darwin" ]]; then
  xattr -d com.apple.quarantine "$install_path.new" 2>/dev/null || true
  if ! codesign -v --strict "$install_path.new" 2>/dev/null; then
    codesign -s - -f "$install_path.new" 2>/dev/null || true
  fi
fi

mv -f "$install_path.new" "$install_path"
OFFICECLI_SKIP_UPDATE=1 "$install_path" --version
echo "OfficeCLI installed at $install_path"
