#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -n "${MAVEN_HOME:-}" ]]; then
  maven="$MAVEN_HOME/bin/mvn"
else
  maven="$(command -v mvn || true)"
fi

if [[ ! -x "$maven" ]]; then
  echo "Maven was not found. Add mvn to PATH or set MAVEN_HOME." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found on PATH." >&2
  exit 1
fi
if ! command -v swiftc >/dev/null 2>&1; then
  echo "swiftc is required to build the macOS Vision OCR helper." >&2
  exit 1
fi

mkdir -p "$project_root/.runtime/bin"
swiftc -O "$project_root/rag/vision_ocr.swift" -o "$project_root/.runtime/bin/vision-ocr"

cd "$project_root/web"
npm run build

maven_args=(-s "$project_root/scripts/maven-settings.xml" -DskipTests package)
if [[ -n "${MAVEN_REPO_LOCAL:-}" ]]; then
  maven_args=(-Dmaven.repo.local="$MAVEN_REPO_LOCAL" "${maven_args[@]}")
fi
cd "$project_root/backend"
"$maven" "${maven_args[@]}"
