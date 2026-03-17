# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Custom resource Lambda that adds a delay after RTB Fabric Gateway creation.

CloudFormation may report a gateway as CREATE_COMPLETE before RTB Fabric has
finished internal provisioning. This function sleeps to allow the gateway to
fully initialize before dependent resources (like Fabric Links) are created.
"""

import time
import logging
from crhelper import CfnResource

logger = logging.getLogger(__name__)
helper = CfnResource(json_logging=False, log_level="INFO", boto_level="CRITICAL")


@helper.create
@helper.update
def wait_for_gateway(event, context):
    gateway_id = event["ResourceProperties"]["GatewayId"]
    logger.info(f"Sleeping 30s to allow gateway {gateway_id} to finish provisioning")
    time.sleep(30)
    logger.info("Sleep complete")
    helper.Data.update({"GatewayId": gateway_id})


@helper.delete
def on_delete(event, context):
    logger.info("Delete - no action required")


def event_handler(event, context):
    helper(event, context)
