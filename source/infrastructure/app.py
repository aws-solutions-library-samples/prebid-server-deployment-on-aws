# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import logging
import sys
from pathlib import Path

from aws_cdk import App, CfnOutput
from aws_solutions.cdk import CDKSolution

from prebid_server.prebid_server_stack import PrebidServerStack

# Add the loadtest directory to the Python path to import BidderSimulatorStack
sys.path.insert(0, str(Path(__file__).parent.parent / "loadtest" / "bidder_simulator"))
from bidder_simulator_stack import BidderSimulatorStack

solution = CDKSolution(cdk_json_path=Path(__file__).parent.absolute() / "cdk.json")

logger = logging.getLogger("cdk-helper")


def synthesizer():
    return CDKSolution(
        cdk_json_path=Path(__file__).parent.absolute() / "cdk.json"
    ).synthesizer


@solution.context.requires("SOLUTION_NAME")
@solution.context.requires("SOLUTION_ID")
@solution.context.requires("SOLUTION_VERSION")
@solution.context.requires("BUCKET_NAME")
def build_app(context):
    app = App(context=context)
    
    # Read context flags for bidder simulator and analytics
    deploy_bidding_simulator = app.node.try_get_context("deployBiddingSimulator")
    enable_log_analytics = app.node.try_get_context("enableLogAnalytics")
    include_rtb_fabric = app.node.try_get_context("includeRtbFabric")
    
    # Convert to boolean (defaults to False if not provided)
    # CDK context values come through as strings, so check for both bool and string values
    deploy_bidding_simulator = deploy_bidding_simulator in [True, 'true', 'True']
    enable_log_analytics = enable_log_analytics in [True, 'true', 'True']
    includeRtbFabric = include_rtb_fabric in [True, 'true', 'True']
    
    # Conditionally deploy bidder simulator stack
    simulator_endpoint = None
    responder_gateway_id = None
    bidder_simulator_vpc_id = None
    bidder_simulator_alb_sg_id = None
    bidder_simulator_route_table_ids = None
    
    if deploy_bidding_simulator:
        bidder_simulator_stack = BidderSimulatorStack(
            app,
            "BiddingServerSimulator",
            include_rtb_fabric=includeRtbFabric,
        )
        
        # Export the ALB DNS name for reference
        CfnOutput(
            bidder_simulator_stack,
            "BidderSimulatorEndpoint",
            value=f"http://{bidder_simulator_stack.alb.load_balancer_dns_name}",
            description="Bidder Simulator ALB endpoint URL"
        )
        
        # Pass the ALB DNS name as a Token (not resolved) to create proper dependency
        # CDK will handle the cross-stack reference automatically
        # When RTB Fabric is enabled, don't pass the ALB endpoint — the PBS stack
        # will build the simulator_endpoint from the Fabric Link URL instead
        if not includeRtbFabric:
            simulator_endpoint = f"http://{bidder_simulator_stack.alb.load_balancer_dns_name}"
        
        # If RTB Fabric is enabled, pass the Responder Gateway ID to PBS stack
        # This enables the PBS stack to create the Fabric Link
        if include_rtb_fabric and deploy_bidding_simulator:
            # Pass the Responder Gateway ID as a Token for cross-stack reference
            responder_gateway_id = bidder_simulator_stack.responder_gateway.attr_gateway_id
        
        # If VPC peering is needed (RTB Fabric disabled), pass VPC ID and ALB security group ID to PBS stack
        # This enables the PBS stack to create VPC peering and update security groups
        if not include_rtb_fabric:
            # Pass Bidder Simulator VPC ID for VPC peering
            bidder_simulator_vpc_id = bidder_simulator_stack.bidder_vpc.vpc_id
            # Pass ALB security group ID for security group rule updates
            bidder_simulator_alb_sg_id = bidder_simulator_stack.alb_security_group.security_group_id
            # Pass route table IDs for adding routes in Bidder Simulator VPC
            bidder_simulator_route_table_ids = bidder_simulator_stack.private_route_table_ids
    
    # Deploy main Prebid Server stack with simulator endpoint and analytics flag
    prebid_server_stack = PrebidServerStack(
        app,
        PrebidServerStack.name,
        description=PrebidServerStack.description,
        template_filename=PrebidServerStack.template_filename,
        synthesizer=synthesizer(),
        simulator_endpoint=simulator_endpoint,
        enable_log_analytics=enable_log_analytics,
        include_rtb_fabric=includeRtbFabric,
        responder_gateway_id=responder_gateway_id,
        bidder_simulator_vpc_id=bidder_simulator_vpc_id,
        bidder_simulator_alb_sg_id=bidder_simulator_alb_sg_id,
        bidder_simulator_route_table_ids=bidder_simulator_route_table_ids,
    )

    return app.synth(validate_on_synthesis=True, skip_validation=False)


if __name__ == "__main__":
    build_app()
