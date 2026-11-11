#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# simulator-fabric-link.sh — thin wrapper around deployment/simulator_fabric_link.py.
#
# Manages the RTB Fabric Link lifecycle for the Bidder Simulator. The Fabric
# Link is intentionally NOT managed by CloudFormation (the CDK stacks create
# only the Requester/Responder Gateways). This script creates, deletes, and
# reports the status of the link via direct API calls and persists the link ID
# in SSM Parameter Store.
#
# Usage:
#   deployment/simulator-fabric-link.sh <create|delete|status> [options]
#
# All arguments are passed through to simulator_fabric_link.py. See that script
# (or run with no subcommand) for the full option list.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
PY_SCRIPT="$SCRIPT_DIR/simulator_fabric_link.py"

if [ ! -f "$PY_SCRIPT" ]; then
    echo "ERROR: simulator_fabric_link.py not found at $PY_SCRIPT" >&2
    exit 1
fi

REQUIREMENTS="$SCRIPT_DIR/requirements-fabric-link.txt"
VENV_DIR="$SCRIPT_DIR/.venv-fabric-link"

if [ ! -f "$REQUIREMENTS" ]; then
    echo "ERROR: requirements-fabric-link.txt not found at $REQUIREMENTS" >&2
    exit 1
fi

if ! command -v python3 > /dev/null 2>&1; then
    echo "ERROR: python3 not found on PATH" >&2
    exit 1
fi

# Install the script's dependencies (boto3 and the AWS CLI) into a dedicated
# virtual environment. The script shells out to `aws` for RTB Fabric calls, and
# only the pinned AWS CLI from requirements-fabric-link.txt is known to include
# the rtbfabric service model, so the venv's bin directory goes first on PATH.
# A dedicated venv also avoids installing into a system Python that refuses
# pip installs (PEP 668).
#
# All install output goes to stderr: deploy.sh captures this script's stdout
# as the Fabric Link URL, so nothing else may be written to stdout.
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating Python environment for the Fabric Link script at $VENV_DIR ..." >&2
    if ! python3 -m venv "$VENV_DIR" >&2; then
        echo "ERROR: could not create a Python virtual environment. Install the python3 venv module and retry." >&2
        exit 1
    fi
fi

echo "Installing Fabric Link script dependencies ..." >&2
if ! "$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check -r "$REQUIREMENTS" >&2; then
    echo "ERROR: failed to install dependencies from $REQUIREMENTS" >&2
    exit 1
fi

export PATH="$VENV_DIR/bin:$PATH"
exec "$VENV_DIR/bin/python" "$PY_SCRIPT" "$@"
