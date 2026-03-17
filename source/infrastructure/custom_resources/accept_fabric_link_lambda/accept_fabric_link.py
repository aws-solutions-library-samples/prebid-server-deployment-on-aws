# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Custom resource Lambda function to accept RTB Fabric Link.

This function accepts a link request between RTB Fabric gateways when both
gateways are in the same AWS account. The link must be accepted by the
responder gateway owner before it becomes active.
"""

import boto3
import logging
from crhelper import CfnResource

logger = logging.getLogger(__name__)
helper = CfnResource(json_logging=False, log_level="INFO", boto_level="CRITICAL")

rtbfabric_client = boto3.client("rtbfabric")


@helper.create
@helper.update
def accept_link(event, context):
    """
    Accept RTB Fabric Link on CREATE and UPDATE events.
    
    Args:
        event: CloudFormation custom resource event
        context: Lambda context object
        
    Returns:
        dict: Response data with link status
    """
    logger.info("Accepting RTB Fabric Link")
    
    # Get parameters from event
    gateway_id = event["ResourceProperties"]["GatewayId"]
    link_id = event["ResourceProperties"]["LinkId"]
    error_log_sampling = float(event["ResourceProperties"].get("ErrorLogSampling", 100))
    filter_log_sampling = float(event["ResourceProperties"].get("FilterLogSampling", 100))
    
    try:
        # Accept the link
        response = rtbfabric_client.accept_link(
            gatewayId=gateway_id,
            linkId=link_id,
            logSettings={
                "applicationLogs": {
                    "sampling": {
                        "errorLog": error_log_sampling,
                        "filterLog": filter_log_sampling
                    }
                }
            }
        )
        
        logger.info(f"Link accepted successfully. Status: {response['status']}")
        
        # Return link details
        helper.Data.update({
            "LinkId": response["linkId"],
            "Status": response["status"],
            "GatewayId": response["gatewayId"],
            "PeerGatewayId": response["peerGatewayId"]
        })
        
    except Exception as e:
        logger.error(f"Failed to accept link: {str(e)}")
        raise


@helper.delete
def delete_link_acceptance(event, context):
    """
    No-op on DELETE - link deletion is handled by CloudFormation.
    
    Args:
        event: CloudFormation custom resource event
        context: Lambda context object
    """
    logger.info("Link acceptance deletion - no action required")
    # Link deletion is handled by CloudFormation when the Link resource is deleted


def event_handler(event, context):
    """
    Lambda handler function.
    
    Args:
        event: CloudFormation custom resource event
        context: Lambda context object
    """
    helper(event, context)
