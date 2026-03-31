touch create_selectable_ctx_models.sh
cat > create_selectable_ctx_models.sh <<'EOF'
#!/usr/bin/env sh

set -eu

echo "=== Ollama Selectable Context Model Builder ==="

printf "Base model name (example: nemotron-3-nano:30b): "
read BASE_MODEL

if [ -z "${BASE_MODEL}" ]; then
  echo "Error: base model name cannot be empty."
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Error: ollama command not found."
  exit 1
fi

echo
echo "Checking base model: $BASE_MODEL"
if ! ollama show "$BASE_MODEL" >/dev/null 2>&1; then
  echo "Base model not found locally."
  echo "Please pull/run it first, for example:"
  echo "  ollama run $BASE_MODEL"
  exit 1
fi

# 可用的 ctx 對應
CTX_4K=4500
CTX_8K=9000
CTX_16K=18000
CTX_32K=36000
CTX_64K=72000
CTX_128K=144000

echo
echo "Available context presets:"
echo "  4k   -> $CTX_4K"
echo "  8k   -> $CTX_8K"
echo "  16k  -> $CTX_16K"
echo "  32k  -> $CTX_32K"
echo "  64k  -> $CTX_64K"
echo "  128k -> $CTX_128K"
echo
printf "Enter the ctx presets to create (example: 4k 16k 64k), or 'all': "
read SELECTED

if [ -z "${SELECTED}" ]; then
  echo "Error: no ctx preset selected."
  exit 1
fi

OUT_DIR="./ctx_modelfiles_${BASE_MODEL%%:*}"
mkdir -p "$OUT_DIR"

create_model() {
  LABEL="$1"
  CTX="$2"
  NEW_MODEL="${BASE_MODEL}-${LABEL}"
  MODELFILE_PATH="${OUT_DIR}/Modelfile.${LABEL}"

  echo
  echo "Creating Modelfile for ${NEW_MODEL} (num_ctx=${CTX})"

  cat > "$MODELFILE_PATH" <<EOM
FROM ${BASE_MODEL}
PARAMETER num_ctx ${CTX}
EOM

  echo "Running: ollama create ${NEW_MODEL} -f ${MODELFILE_PATH}"
  ollama create "${NEW_MODEL}" -f "${MODELFILE_PATH}"
  echo "Done: ${NEW_MODEL}"
}

handle_one() {
  ITEM="$1"
  case "$ITEM" in
    4k)   create_model "4k"   "$CTX_4K" ;;
    8k)   create_model "8k"   "$CTX_8K" ;;
    16k)  create_model "16k"  "$CTX_16K" ;;
    32k)  create_model "32k"  "$CTX_32K" ;;
    64k)  create_model "64k"  "$CTX_64K" ;;
    128k) create_model "128k" "$CTX_128K" ;;
    *)
      echo
      echo "Warning: unknown preset '$ITEM' skipped."
      ;;
  esac
}

if [ "$SELECTED" = "all" ]; then
  handle_one 4k
  handle_one 8k
  handle_one 16k
  handle_one 32k
  handle_one 64k
  handle_one 128k
else
  for ITEM in $SELECTED; do
    handle_one "$ITEM"
  done
fi

echo
echo "Finished."
echo "You can list models with:"
echo "  ollama list"
EOF

chmod +x create_selectable_ctx_models.sh