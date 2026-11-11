#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Prebid Server container build tooling — base-image selection contract.
#
# Implements the dual-base selection contract (Requirements 3.1, 3.2, 3.4, 3.5):
#   - --base al2023 | alpine  selects deployment/ecr/prebid-server/Dockerfile.<base>
#   - default base is al2023 when --base is unset (design FR3.3)
#   - the base value is validated against the closed set in docker-build-config.json
#     BEFORE any Docker invocation; an unsupported value exits non-zero with a
#     message naming the invalid value (fail before side effects, Req 3.5)
#
# The closed set {al2023, alpine}, the default base, and the base -> Dockerfile
# mapping are read from docker-build-config.json (keys SUPPORTED_BASES,
# DEFAULT_BASE, BASE_DOCKERFILES) so the resolution contract has a single source
# of truth shared with container-image-construct.ts.
#
# This script owns ONLY the build-tooling / base-selection contract. It does not
# modify the bodies of Dockerfile.al2023 or Dockerfile.alpine.

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Resolve directories relative to this script so the tooling is invocation-location
# independent.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$SCRIPT_DIR/prebid-server"
CONFIG_FILE="$DOCKER_DIR/docker-build-config.json"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--base <al2023|alpine>] [--tag <name>] [--no-cache] [-- <extra docker build args>]

Options:
  --base BASE     Container base image variant. Supported: al2023 (default), alpine.
                  Selects deployment/ecr/prebid-server/Dockerfile.<BASE>.
  --tag NAME      Image tag to apply (default: prebid-server).
  --no-cache      Pass --no-cache to docker build.
  --dry-run       Resolve and validate --base, print the resolved Dockerfile, and exit
                  WITHOUT invoking Docker (used to exercise the validation contract).
  -h, --help      Show this help.

Any arguments after a literal -- are forwarded verbatim to 'docker build'.
EOF
}

# Defaults
BASE_IMAGE=""
IMAGE_TAG="prebid-server"
NO_CACHE=""
DRY_RUN="false"
EXTRA_DOCKER_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --base)
            BASE_IMAGE="$2"
            shift 2
            ;;
        --tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --no-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_DOCKER_ARGS=("$@")
            break
            ;;
        *)
            print_error "Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
done

# The config file is the single source of truth for the selection contract.
if [ ! -f "$CONFIG_FILE" ]; then
    print_error "Docker build config not found: $CONFIG_FILE"
    exit 1
fi

# Reader that pulls a value out of docker-build-config.json using node. node is
# always present in this package's build toolchain (the build runs npm/npx/tsc),
# whereas python3 is not guaranteed on every build host (e.g. AL2_x86_64), so
# node keeps this portable. The config path and key are passed as argv, not
# interpolated into the program body, per shell conventions. No secrets involved.
read_config() {
    # $1 = mode: "default_base" | "supported_bases" | "dockerfile"
    # $2 = base value (only for mode=dockerfile)
    node - "$CONFIG_FILE" "$1" "${2:-}" <<'JS'
const fs = require("fs");
const [, , configFile, mode, base] = process.argv;
const cfg = JSON.parse(fs.readFileSync(configFile, "utf8"));

if (mode === "default_base") {
    process.stdout.write((cfg.DEFAULT_BASE ?? "al2023") + "\n");
} else if (mode === "supported_bases") {
    process.stdout.write((cfg.SUPPORTED_BASES ?? []).join(" ") + "\n");
} else if (mode === "dockerfile") {
    // Empty output signals "no mapping"; the caller treats that as invalid.
    process.stdout.write(((cfg.BASE_DOCKERFILES ?? {})[base] ?? "") + "\n");
}
JS
}

# Resolve the default base from config when --base is unset (design FR3.3).
if [ -z "$BASE_IMAGE" ]; then
    set +e
    BASE_IMAGE="$(read_config default_base)"
    DEFAULT_READ_EXIT=$?
    set -e
    if [ $DEFAULT_READ_EXIT -ne 0 ] || [ -z "$BASE_IMAGE" ]; then
        print_error "Failed to resolve DEFAULT_BASE from $CONFIG_FILE"
        exit 1
    fi
    print_info "No --base supplied; defaulting to '$BASE_IMAGE'."
fi

# Read the closed set of supported bases from config.
set +e
SUPPORTED_BASES="$(read_config supported_bases)"
SUPPORTED_READ_EXIT=$?
set -e
if [ $SUPPORTED_READ_EXIT -ne 0 ] || [ -z "$SUPPORTED_BASES" ]; then
    print_error "Failed to read SUPPORTED_BASES from $CONFIG_FILE"
    exit 1
fi

# Validate --base against the closed set BEFORE any Docker invocation (Req 3.5).
BASE_IS_SUPPORTED="false"
for supported in $SUPPORTED_BASES; do
    if [ "$BASE_IMAGE" = "$supported" ]; then
        BASE_IS_SUPPORTED="true"
        break
    fi
done

if [ "$BASE_IS_SUPPORTED" != "true" ]; then
    print_error "Unsupported base image: '$BASE_IMAGE'. Supported values: ${SUPPORTED_BASES// /, }."
    exit 1
fi

# Resolve the base -> Dockerfile mapping from config.
set +e
DOCKERFILE_NAME="$(read_config dockerfile "$BASE_IMAGE")"
DOCKERFILE_READ_EXIT=$?
set -e
if [ $DOCKERFILE_READ_EXIT -ne 0 ] || [ -z "$DOCKERFILE_NAME" ]; then
    print_error "No Dockerfile mapping for base '$BASE_IMAGE' in $CONFIG_FILE (BASE_DOCKERFILES)."
    exit 1
fi

DOCKERFILE_PATH="$DOCKER_DIR/$DOCKERFILE_NAME"
if [ ! -f "$DOCKERFILE_PATH" ]; then
    print_error "Resolved Dockerfile does not exist: $DOCKERFILE_PATH"
    exit 1
fi

print_info "Base image      : $BASE_IMAGE"
print_info "Dockerfile      : $DOCKERFILE_PATH"
print_info "Image tag       : $IMAGE_TAG"

# In dry-run mode, stop here — the validation/resolution contract has been
# exercised without any Docker side effects.
if [ "$DRY_RUN" = "true" ]; then
    print_info "Dry run: skipping docker build."
    # Emit the resolved Dockerfile name on stdout for tooling/tests to capture.
    echo "$DOCKERFILE_NAME"
    exit 0
fi

# Build the image from the docker build context, using the resolved Dockerfile.
print_info "Building container image..."
set +e
docker build $NO_CACHE \
    -f "$DOCKERFILE_PATH" \
    -t "$IMAGE_TAG" \
    "${EXTRA_DOCKER_ARGS[@]}" \
    "$DOCKER_DIR"
BUILD_EXIT=$?
set -e

if [ $BUILD_EXIT -ne 0 ]; then
    print_error "Docker build failed (exit $BUILD_EXIT) for base '$BASE_IMAGE'."
    exit $BUILD_EXIT
fi

print_info "Successfully built '$IMAGE_TAG' from base '$BASE_IMAGE'."
