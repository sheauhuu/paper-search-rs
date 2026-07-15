#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/paper-search-rs-uvx.XXXXXX")
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM

dist_dir="$work_dir/dist"
uv_cache="$work_dir/uv-cache"
uv_tools="$work_dir/uv-tools"
uv_python="$work_dir/uv-python"
cargo_home="$work_dir/cargo-home"
mkdir -p "$dist_dir" "$uv_cache" "$uv_tools" "$uv_python" "$cargo_home"

UV_CACHE_DIR="$uv_cache" \
UV_TOOL_DIR="$uv_tools" \
UV_PYTHON_INSTALL_DIR="$uv_python" \
CARGO_HOME="$cargo_home" \
uvx --from 'maturin>=1.9,<2.0' maturin build \
  --release \
  --locked \
  --bindings bin \
  --out "$dist_dir" \
  --manifest-path "$repo_root/Cargo.toml"

set -- "$dist_dir"/*.whl
[ "$#" -eq 1 ] || {
  echo "expected exactly one wheel, found $#" >&2
  exit 1
}
wheel=$1

wheel_listing=$(unzip -Z1 "$wheel")
printf '%s\n' "$wheel_listing" | grep -Eq '\.data/scripts/paper-search-rs$'
if printf '%s\n' "$wheel_listing" | grep -Eq '\.py$|\.pyc$|/__pycache__/'; then
  echo "wheel contains an unexpected Python module or cache" >&2
  exit 1
fi

metadata_path=$(printf '%s\n' "$wheel_listing" | grep '\.dist-info/METADATA$')
[ -n "$metadata_path" ] || {
  echo "wheel METADATA is missing" >&2
  exit 1
}
metadata=$(unzip -p "$wheel" "$metadata_path")
printf '%s\n' "$metadata" | grep -qx 'Name: paper-search-rs'
printf '%s\n' "$metadata" | grep -qx 'Version: 0.2.0'
if printf '%s\n' "$metadata" | grep -q '^Requires-Dist:'; then
  echo "wheel contains an unexpected Python runtime dependency" >&2
  exit 1
fi

uv_bin=$(command -v uvx)
version_output=$(env \
  PATH=/usr/bin:/bin \
  UV_CACHE_DIR="$uv_cache" \
  UV_TOOL_DIR="$uv_tools" \
  UV_PYTHON_INSTALL_DIR="$uv_python" \
  PAPER_SEARCH_JCR_ENABLED=false \
  RUST_LOG=error \
  "$uv_bin" --from "$wheel" paper-search-rs --version)
printf '%s\n' "$version_output" | grep -qx 'paper-search-rs 0.2.0'

stdout_file="$work_dir/stdout"
env \
  PATH=/usr/bin:/bin \
  UV_CACHE_DIR="$uv_cache" \
  UV_TOOL_DIR="$uv_tools" \
  UV_PYTHON_INSTALL_DIR="$uv_python" \
  PAPER_SEARCH_JCR_ENABLED=false \
  RUST_LOG=error \
  "$uv_bin" --from "$wheel" paper-search-rs </dev/null >"$stdout_file"
[ ! -s "$stdout_file" ] || {
  echo "uvx launcher contaminated MCP stdout on EOF" >&2
  exit 1
}

echo "local uvx smoke passed: $(basename "$wheel")" >&2
