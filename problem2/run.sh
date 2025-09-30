#!/bin/bash

if [ $# -lt 2 ]; then
  echo "Usage: $0 <input_papers.json> <output_dir> [epochs] [batch_size]"
  exit 1
fi

INPUT_FILE="$1"
OUTPUT_DIR="$2"
EPOCHS="${3:-50}"
BATCH_SIZE="${4:-32}"

if [ ! -f "$INPUT_FILE" ]; then
  echo "Error: Input file $INPUT_FILE not found"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

docker run --rm \
  -v "$(realpath $INPUT_FILE)":/data/input/papers.json \
  -v "$(realpath $OUTPUT_DIR)":/data/output \
  arxiv-embeddings:latest \
  /data/input/papers.json /data/output $EPOCHS $BATCH_SIZE

echo "Training complete. Output files saved in $OUTPUT_DIR"
