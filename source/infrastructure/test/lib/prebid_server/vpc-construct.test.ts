// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for VpcConstruct (task 9.5).
// TypeScript-only construct coverage (Req 6.3): asserts presence + key property
// values of every resource VpcConstruct contributes to the synthesized template
// (VPC, subnets, NAT gateways, internet gateway, S3 gateway endpoint + policy).

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";
import { VPC_CIDR } from "../../../lib/shared/stack-constants";

const template = prebidServerTemplate();

describe("VpcConstruct — VPC topology (task 9.5)", () => {
  it("creates exactly one VPC with the configured CIDR and DNS enabled", () => {
    template.resourceCountIs("AWS::EC2::VPC", 1);
    template.hasResourceProperties("AWS::EC2::VPC", {
      CidrBlock: VPC_CIDR,
      EnableDnsHostnames: true,
      EnableDnsSupport: true,
    });
  });

  it("creates 4 subnets (public + private across 2 AZs) and 2 NAT gateways", () => {
    template.resourceCountIs("AWS::EC2::Subnet", 4);
    template.resourceCountIs("AWS::EC2::NatGateway", 2);
    template.resourceCountIs("AWS::EC2::EIP", 2);
  });

  it("creates one internet gateway attached to the VPC", () => {
    template.resourceCountIs("AWS::EC2::InternetGateway", 1);
    template.resourceCountIs("AWS::EC2::VPCGatewayAttachment", 1);
  });

  it("adds an S3 gateway endpoint", () => {
    template.resourceCountIs("AWS::EC2::VPCEndpoint", 1);
    template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
      VpcEndpointType: "Gateway",
      ServiceName: {
        "Fn::Join": ["", ["com.amazonaws.", { Ref: "AWS::Region" }, ".s3"]],
      },
    });
  });

  it("the S3 gateway endpoint policy grants s3:GetObject (starport layer + artifact buckets)", () => {
    template.hasResourceProperties("AWS::EC2::VPCEndpoint", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({ Action: "s3:GetObject", Effect: "Allow" }),
        ]),
      }),
    });
  });
});
