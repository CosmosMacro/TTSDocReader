#!/usr/bin/env bash
set -euo pipefail

# Download Piper binary and a sample French voice into third_party/piper (Linux/macOS)
# Usage: bash scripts/setup_piper.sh [PIPER_VERSION] [VOICE_LANG] [VOICE_NAME]

PIPER_VERSION="${1:-v1.2.0}"
VOICE_LANG="${2:-fr}"
VOICE_NAME="${3:-fr_FR-siwis-medium}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TP_DIR="$ROOT_DIR/third_party"
PIPER_ROOT="$TP_DIR/piper"
BIN_DIR="$PIPER_ROOT/piper"
MODELS_DIR="$PIPER_ROOT/models"

mkdir -p "$BIN_DIR" "$MODELS_DIR"

# Linux x86_64 binary (change asset for macOS/arm64 as needed)
ZIP="$TP_DIR/piper_linux_x86_64.zip"
URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.zip"
echo "Downloading Piper from $URL"
curl -L "$URL" -o "$ZIP"
echo "Extracting to $BIN_DIR"
unzip -o "$ZIP" -d "$BIN_DIR"
rm -f "$ZIP"

# Sample French voice
VOICE_BASE="https://raw.githubusercontent.com/rhasspy/piper-voices/main/${VOICE_LANG}/fr/siwis/medium"
ONNX_URL="$VOICE_BASE/${VOICE_NAME}.onnx"
JSON_URL="$VOICE_BASE/${VOICE_NAME}.onnx.json"

echo "Downloading voice model: $VOICE_NAME"
curl -L "$ONNX_URL" -o "$MODELS_DIR/${VOICE_NAME}.onnx"
curl -L "$JSON_URL" -o "$MODELS_DIR/${VOICE_NAME}.onnx.json"

echo "Done. Set in your .env:"
echo "  PIPER_BIN=$BIN_DIR/piper"
echo "  PIPER_MODEL=$MODELS_DIR/${VOICE_NAME}.onnx"

