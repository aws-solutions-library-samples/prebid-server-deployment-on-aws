// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";

export class VpcConstruct extends Construct {
  public readonly prebidVpc: ec2.Vpc;
  public readonly prebidTaskSubnets: ec2.ISubnet[];

  constructor(
    scope: Construct,
    id: string,
    artifactsBucket: s3.IBucket,
    dockerConfigsBucket: s3.IBucket,
    storedRequestsBucket: s3.IBucket
  ) {
    super(scope, id);

    this.prebidVpc = new ec2.Vpc(this, "PrebidVpc", {
      ipAddresses: ec2.IpAddresses.cidr(constants.VPC_CIDR),
      maxAzs: constants.MAX_AZS,
      natGateways: constants.NAT_GATEWAYS,
      subnetConfiguration: [
        {
          subnetType: ec2.SubnetType.PUBLIC,
          name: constants.PUB_SUBNET_NAME,
          cidrMask: constants.CIDR_MASK,
        },
        {
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          name: constants.PVT_SUBNET_NAME,
          cidrMask: constants.CIDR_MASK,
        },
      ],
    });

    this.prebidTaskSubnets = this.prebidVpc.selectSubnets({
      subnetGroupName: constants.PVT_SUBNET_NAME,
    }).subnets;

    // Suppress cfn_guard on public subnets
    for (const subnet of this.prebidVpc.selectSubnets({ subnetGroupName: constants.PUB_SUBNET_NAME }).subnets) {
      (subnet.node.defaultChild as ec2.CfnSubnet).addMetadata("guard", {
        SuppressedRules: ["SUBNET_AUTO_ASSIGN_PUBLIC_IP_DISABLED"],
      });
    }

    // S3 gateway endpoint
    const s3Endpoint = this.prebidVpc.addGatewayEndpoint("s3_gateway_endpoint", {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });

    s3Endpoint.addToPolicy(
      new iam.PolicyStatement({
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:GetObject"],
        resources: [`arn:aws:s3:::prod-${Aws.REGION}-starport-layer-bucket/*`],
      })
    );

    s3Endpoint.addToPolicy(
      new iam.PolicyStatement({
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:GetObject", "s3:ListBucket"],
        resources: [artifactsBucket.bucketArn, `${artifactsBucket.bucketArn}/*`],
        conditions: { StringEquals: { [constants.RESOURCE_NAMESPACE]: Aws.ACCOUNT_ID } },
      })
    );

    s3Endpoint.addToPolicy(
      new iam.PolicyStatement({
        principals: [new iam.AnyPrincipal()],
        actions: ["s3:GetObject", "s3:ListBucket"],
        resources: [
          `${dockerConfigsBucket.bucketArn}/*`,
          dockerConfigsBucket.bucketArn,
          `${storedRequestsBucket.bucketArn}/*`,
          storedRequestsBucket.bucketArn,
        ],
        conditions: { StringEquals: { [constants.RESOURCE_NAMESPACE]: Aws.ACCOUNT_ID } },
      })
    );
  }
}
