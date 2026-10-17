#!/bin/bash
# Build Docker images for all blocks in block_registry/
# Usage: ./scripts/build_all_images.sh [registry_prefix]

set -e

REGISTRY_PREFIX="${1:-ghcr.io/cerebrum-blocks}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
REGISTRY_DIR="$REPO_ROOT/block_registry"

echo "=============================================="
echo "Cerebrum Block Registry - Docker Build"
echo "Registry: $REGISTRY_PREFIX"
echo "=============================================="

# Build base image first
echo ""
echo "--> Building base image..."
docker build -f "$REGISTRY_DIR/Dockerfile.base" -t cerebrum-block-base:latest "$REPO_ROOT"

# Build each block image
BUILT=0
FAILED=0

for block_dir in "$REGISTRY_DIR"/*/; do
    if [ ! -f "$block_dir/Dockerfile" ]; then
        continue
    fi

    block_name=$(basename "$block_dir")
    image_tag="$REGISTRY_PREFIX/$block_name:latest"

    echo ""
    echo "--> Building $block_name -> $image_tag"

    if docker build -t "$image_tag" "$block_dir"; then
        echo "  [OK] $block_name"
        BUILT=$((BUILT + 1))
    else
        echo "  [FAIL] $block_name"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "=============================================="
echo "Build complete: $BUILT succeeded, $FAILED failed"
echo "=============================================="

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
