#!/usr/bin/env bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# -----------------------------------------------------------------------------
# PURPOSE:
# This entrypoint script is used to start the Prebid Server container.
#
# An environment variable named ECS_CONTAINER_METADATA_URI_V4
# is injected by ECS into each container. The variable contains a URI that
# is used to retrieve container status and data.
#
# See:
# https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-metadata-endpoint-v4.html
#
# The entrypoint defined below retrieves the data and parses the
# container's unique ID from it and uses the ID to ensure
# log data is written to a unique directory under /mnt/efs/.
# The container ID is also included with logs sent directly
# to CloudWatch.
#
# If the environment variable ECS_CONTAINER_METADATA_URI_V4 is not set,
# the string "default-container-id" is returned instead so that the
# container can be run locally.
#
# Metrics are sent to /mnt/efs/metrics folder also using the container ID
# in the path. Files have the name prebid-metrics.log.
#
# The default Java executable entry point specified in this script can be
# customized or replaced with a different command or executable.
# ------------------------------------------------------------------------------

set -x

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Initializing container entrypoint script..."

PREBID_CONFIGS_DIR="/prebid-configs"

CONTAINER_ID=$(if [ -z "$ECS_CONTAINER_METADATA_URI_V4" ]; then
    echo "default-container-id"
else
    DOCKER_ID=$(curl -s "${ECS_CONTAINER_METADATA_URI_V4}/task" | grep -o '"DockerId":"[^"]*"' | cut -d'"' -f4)
    # Take only the first part before any dash
    echo "${DOCKER_ID%%-*}" | tr -d '\n\r' || echo "default-container-id"
fi)

# Check if CONTAINER_ID appears to be duplicated
if [[ ${#CONTAINER_ID} -gt 32 ]]; then
    # Take only the first 32 characters
    CONTAINER_ID="${CONTAINER_ID:0:32}"
fi

echo "{\"containerId\":\"${CONTAINER_ID}\"}"

# Generate a self-signed SSL token for encrypting the HTTPS session between
# this prebid-server-java process and the application load balancer in EC2.
# The following SSL env vars are used in ${PREBID_CONFIGS_DIR}/prebid-config.yaml
export SSL_KEYSTORE_PATH="${PREBID_CONFIGS_DIR}/keystore.jks"
export SSL_KEYSTORE_PASS="$(openssl rand -base64 16)"

"${JAVA_HOME}/bin/keytool" -genkeypair \
    -alias prebidserver \
    -keyalg RSA \
    -keysize 2048 \
    -validity 3650 \
    -keystore "${SSL_KEYSTORE_PATH}" \
    -dname "CN=prebidserver.local, OU=AWS, O=Solutions, L=Seattle, ST=WA, C=US" \
    -storepass "${SSL_KEYSTORE_PASS}" \
    -keypass "${SSL_KEYSTORE_PASS}"

"${JAVA_HOME}/bin/java" \
    -DcontainerId="${CONTAINER_ID}" \
    -DPREBID_CONFIGS_DIR="${PREBID_CONFIGS_DIR}" \
    -Dlogging.config="${PREBID_CONFIGS_DIR}/prebid-logging.xml" \
    -XX:+UseParallelGC \
    -jar target/prebid-server.jar \
    --spring.config.additional-location="${PREBID_CONFIGS_DIR}/prebid-config.yaml"
