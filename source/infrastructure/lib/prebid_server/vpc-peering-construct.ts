// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, CfnOutput, Tags } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Construct } from "constructs";
import { VpcConstruct } from "./vpc-construct";
import { StackParams } from "./stack-cfn-parameters";

/**
 * Creates a VPC peering connection between the Prebid Server and Bidder Simulator VPCs.
 *
 * All resources are gated by the `UseVpcPeering` CfnCondition from StackParams:
 *   - `UseVpcPeering` is true when `SimulatorVpcId != ""`.
 *   - When RTB Fabric is the connectivity model, `SimulatorVpcId` is empty, so
 *     none of these resources are created (mutual exclusivity).
 *
 * VPC Peering Configuration:
 *   - Automatically accepted (both VPCs in the same account)
 *   - Routes added in BOTH VPCs (Prebid private subnets + the two simulator route tables)
 *   - Bidder Simulator ALB security group updated (standalone CfnSecurityGroupIngress)
 *     to allow HTTP from the Prebid Server VPC CIDR
 *
 * Ported from the Mainline `vpc_peering_construct.py` (landed CFN-parameter migration).
 */
export class VpcPeeringConstruct extends Construct {
  public readonly vpcPeeringConnection: ec2.CfnVPCPeeringConnection;

  constructor(scope: Construct, id: string, vpcConstruct: VpcConstruct, stackParams: StackParams) {
    super(scope, id);

    const condition = stackParams.useVpcPeering;

    // Create the VPC peering connection.
    this.vpcPeeringConnection = new ec2.CfnVPCPeeringConnection(this, "PrebidServerVpcPeering", {
      peerVpcId: stackParams.simulatorVpcIdParam.valueAsString,
      vpcId: vpcConstruct.prebidVpc.vpcId,
    });
    this.vpcPeeringConnection.cfnOptions.condition = condition;
    Tags.of(this.vpcPeeringConnection).add("Name", `${Aws.STACK_NAME}-PrebidServer-VpcPeering`);

    // Routes in the Prebid Server VPC private subnets → Bidder Simulator VPC CIDR (10.1.0.0/16).
    const privateSubnets = vpcConstruct.prebidVpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS });
    privateSubnets.subnets.forEach((subnet, i) => {
      const route = new ec2.CfnRoute(this, `PrebidToBidderRoute${i}`, {
        routeTableId: subnet.routeTable.routeTableId,
        destinationCidrBlock: "10.1.0.0/16",
        vpcPeeringConnectionId: this.vpcPeeringConnection.ref,
      });
      route.cfnOptions.condition = condition;
    });

    // Routes in the Bidder Simulator VPC using the two route table ID parameters.
    const route1 = new ec2.CfnRoute(this, "BidderToPrebidRoute0", {
      routeTableId: stackParams.simulatorRouteTableId1Param.valueAsString,
      destinationCidrBlock: "10.8.0.0/16", // Prebid Server VPC CIDR
      vpcPeeringConnectionId: this.vpcPeeringConnection.ref,
    });
    route1.cfnOptions.condition = condition;

    const route2 = new ec2.CfnRoute(this, "BidderToPrebidRoute1", {
      routeTableId: stackParams.simulatorRouteTableId2Param.valueAsString,
      destinationCidrBlock: "10.8.0.0/16", // Prebid Server VPC CIDR
      vpcPeeringConnectionId: this.vpcPeeringConnection.ref,
    });
    route2.cfnOptions.condition = condition;

    // Update the Bidder Simulator ALB security group to allow HTTP from the
    // Prebid Server VPC CIDR (standalone ingress rule, not an imported-SG addIngressRule).
    const sgIngress = new ec2.CfnSecurityGroupIngress(this, "BidderAlbIngressFromPrebid", {
      groupId: stackParams.simulatorAlbSgIdParam.valueAsString,
      ipProtocol: "tcp",
      fromPort: 80,
      toPort: 80,
      cidrIp: "10.8.0.0/16", // Prebid Server VPC CIDR
      description: "Allow HTTP from Prebid Server VPC via peering",
    });
    sgIngress.cfnOptions.condition = condition;

    // Output the VPC peering connection ID for reference.
    // Mainline pins CfnOutput(..., key="VpcPeeringConnectionId"). Without an override CDK emits
    // VpcPeeringVpcPeeringConnectionId<hash>. Pin it flat for output-naming parity.
    // overrideLogicalId is compatible with a conditional output — the .condition (UseVpcPeering)
    // assignment below is preserved.
    const peeringOutput = new CfnOutput(this, "VpcPeeringConnectionId", {
      value: this.vpcPeeringConnection.ref,
      description: "VPC Peering Connection ID between Prebid Server and Bidder Simulator VPCs",
    });
    peeringOutput.condition = condition;
    peeringOutput.overrideLogicalId("VpcPeeringConnectionId");
  }
}
