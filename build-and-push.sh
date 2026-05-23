#!/bin/bash
# Build and push fitness-os-backend image to ghcr.io for linux/amd64.
set -e

IMAGE_NAME="ghcr.io/marava-tech/fitness-os-backend"
TAG="latest"

echo "Building ${IMAGE_NAME}:${TAG} for linux/amd64..."

docker buildx build \
    --platform linux/amd64 \
    --tag ${IMAGE_NAME}:${TAG} \
    --file Dockerfile \
    --push \
    .

echo "Done: ${IMAGE_NAME}:${TAG}"
