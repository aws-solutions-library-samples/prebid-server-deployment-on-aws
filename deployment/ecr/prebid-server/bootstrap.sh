#!/usr/bin/env bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# -----------------------------------------------------------------------------------------------------------------------------------------------------------------
# PURPOSE:
#  * Download Prebid Server configuration files and scripts from an S3 bucket.
#  * The S3 bucket name is obtained from the environment variable DOCKER_CONFIGS_S3_BUCKET_NAME.
#  * The configuration files are downloaded into a local /prebid-configs directory.
#  * The default and current configuration files are fetched from two specific prefixes in the S3 bucket.
#  * After download, the script verifies that essential configuration files exist.
#  * The entrypoint script is then executed to start the Docker containers.
# -----------------------------------------------------------------------------------------------------------------------------------------------------------------

set -euo pipefail

# Set variables
PREBID_CONFIGS_DIR="prebid-configs"
ENTRYPOINT_SCRIPT="entrypoint.sh"
REQUIRED_CONFIG_FILES="${ENTRYPOINT_SCRIPT} prebid-config.yaml prebid-logging.xml prebid-analytics-logging.xml"
ENTRYPOINT_DIR="../${PREBID_CONFIGS_DIR}"

# Check if the S3 bucket environment variable is set
if [ -z "${DOCKER_CONFIGS_S3_BUCKET_NAME:-}" ]; then
    echo "Error: DOCKER_CONFIGS_S3_BUCKET_NAME environment variable is not set"
    exit 1
else
    # Define S3 paths
    DEFAULT_S3_PATH="s3://${DOCKER_CONFIGS_S3_BUCKET_NAME}/prebid-server/default/"
    CURRENT_S3_PATH="s3://${DOCKER_CONFIGS_S3_BUCKET_NAME}/prebid-server/current/"
    
    echo "Cleaning up and recreating ${ENTRYPOINT_DIR}"
    rm -rvf "${ENTRYPOINT_DIR}" || { echo "Failed to remove ${ENTRYPOINT_DIR}"; exit 1; }
    mkdir -pv "${ENTRYPOINT_DIR}" || { echo "Failed to create ${ENTRYPOINT_DIR}"; exit 1; }

    # Download default Prebid configuration files from S3
    echo "Downloading default configuration files from S3 bucket: ${DEFAULT_S3_PATH}"
    if aws s3 cp "$DEFAULT_S3_PATH" "$ENTRYPOINT_DIR" --recursive --exclude "README.md"; then
        echo "Successfully downloaded default configuration files"
    else
        echo "Failed to download default configuration files"
        exit 1
    fi

    # Download current Prebid configuration files from S3 (ignore if missing)
    echo "Downloading current configuration files from S3 bucket: ${CURRENT_S3_PATH}"
    if aws s3 cp "$CURRENT_S3_PATH" "$ENTRYPOINT_DIR" --recursive --exclude "README.md"; then
        echo "Successfully downloaded current configuration files"
    else
        echo "Warning: Failed to download current configuration files, proceeding without them"
    fi
fi

# Check if all required configuration files exist
for required_config_file in $REQUIRED_CONFIG_FILES; do
    echo "Checking if ${required_config_file} exists"
    if [ ! -f "${ENTRYPOINT_DIR}/${required_config_file}" ]; then
       echo "Error: Required configuration file ${required_config_file} is missing"
       exit 1
    fi
done

# Execute the entrypoint script to start Docker containers
echo "Executing ${ENTRYPOINT_SCRIPT}"
sh "${ENTRYPOINT_DIR}/${ENTRYPOINT_SCRIPT}" || { echo "Failed to execute ${ENTRYPOINT_SCRIPT}"; exit 1; }
