// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, CfnOutput, CfnResource, CustomResource, Duration } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as rtbfabric from "aws-cdk-lib/aws-rtbfabric";
import { Construct } from "constructs";
import { CrHelperLayer, pythonAssetCode } from "../shared/lambda-helpers";
import { VpcConstruct } from "./vpc-construct";
import { StackParams } from "./stack-cfn-parameters";
import * as constants from "../shared/stack-constants";
import * as path from "path";

/**
 * Creates the RTB Fabric Requester Gateway with a WaitForGateway readiness check.
 *
 * Resources are gated by CfnConditions from StackParams:
 *   - Requester Gateway (+ SecurityGroup + CfnOutputs + WaitForGateway custom
 *     resource): created when `HasRtbRequesterGateway` is true
 *     (`EnableRtbRequesterGateway=true`).
 *
 * The Fabric Link lifecycle is managed *externally* by
 * `deployment/simulator_fabric_link.py` — there is NO in-CDK `CfnLink`, no
 * Accept Lambda, and no in-CDK Fabric Link acceptance custom resource. The
 * WaitForGateway custom resource ensures the gateway is fully provisioned before
 * the external script creates the Fabric Link (CloudFormation reports
 * CREATE_COMPLETE before RTB Fabric finishes internal provisioning, which causes
 * a 409 "not ready" error on Link creation).
 *
 * Ported from the Mainline `rtb_fabric_construct.py` (landed CFN-parameter migration).
 */
export class RtbFabricConstruct extends Construct {
  public readonly requesterGateway: rtbfabric.CfnRequesterGateway;
  public requesterGatewaySecurityGroup!: ec2.SecurityGroup;

  private readonly stackParams: StackParams;

  constructor(scope: Construct, id: string, vpcConstruct: VpcConstruct, stackParams: StackParams) {
    super(scope, id);
    this.stackParams = stackParams;

    this.requesterGateway = this.createRequesterGateway(vpcConstruct);
    this.createWaitForGateway();
  }

  /**
   * Create the RTB Fabric Requester Gateway (conditional on HasRtbRequesterGateway).
   * - Attached to the PBS VPC
   * - IPv4 HTTPS (443) traffic only
   * - Security group allows HTTPS from the PBS application
   */
  private createRequesterGateway(vpcConstruct: VpcConstruct): rtbfabric.CfnRequesterGateway {
    const condition = this.stackParams.hasRtbRequesterGateway;

    this.requesterGatewaySecurityGroup = new ec2.SecurityGroup(this, "RequesterGatewaySecurityGroup", {
      vpc: vpcConstruct.prebidVpc,
      description: "Security group for RTB Fabric Requester Gateway",
      allowAllOutbound: true,
    });
    (this.requesterGatewaySecurityGroup.node.defaultChild as ec2.CfnSecurityGroup).cfnOptions.condition = condition;

    this.requesterGatewaySecurityGroup.addIngressRule(
      ec2.Peer.ipv4(vpcConstruct.prebidVpc.vpcCidrBlock),
      ec2.Port.tcp(443),
      "Allow HTTPS from PBS application"
    );

    const privateSubnets = vpcConstruct.prebidVpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS });

    const requesterGateway = new rtbfabric.CfnRequesterGateway(this, "RequesterGateway", {
      vpcId: vpcConstruct.prebidVpc.vpcId,
      subnetIds: [privateSubnets.subnets[0].subnetId],
      securityGroupIds: [this.requesterGatewaySecurityGroup.securityGroupId],
      description: "RTB Fabric Requester Gateway for PBS",
      tags: [{ key: "Name", value: `${Aws.STACK_NAME}-PBS-RequesterGateway` }],
    });
    requesterGateway.cfnOptions.condition = condition;

    const gatewayIdOutput = new CfnOutput(this, "RequesterGatewayId", {
      value: requesterGateway.attrGatewayId,
      description: "RTB Fabric Requester Gateway ID",
    });
    gatewayIdOutput.condition = condition;
    // Mainline pins CfnOutput(..., key="RequesterGatewayId"). deployment/simulator_fabric_link.py
    // reads this output by EXACT key (outputs.get("RequesterGatewayId")), so the logical ID must
    // be flat (no path prefix / hash suffix). overrideLogicalId is compatible with a conditional
    // output — the .condition assignment above is preserved.
    gatewayIdOutput.overrideLogicalId("RequesterGatewayId");

    const gatewayArnOutput = new CfnOutput(this, "RequesterGatewayArn", {
      value: requesterGateway.attrArn,
      description: "RTB Fabric Requester Gateway ARN",
    });
    gatewayArnOutput.condition = condition;
    // Mainline pins CfnOutput(..., key="RequesterGatewayArn"). Parity with mainline output naming.
    gatewayArnOutput.overrideLogicalId("RequesterGatewayArn");

    return requesterGateway;
  }

  /**
   * Create the WaitForGateway custom resource (conditional on HasRtbRequesterGateway).
   * Ensures the Requester Gateway is fully provisioned before any downstream
   * operation (e.g. Fabric Link creation via simulator_fabric_link.py).
   */
  private createWaitForGateway(): void {
    const condition = this.stackParams.hasRtbRequesterGateway;

    const waitRole = new iam.Role(this, "WaitForGatewayFunctionRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      inlinePolicies: {
        LambdaFunctionServiceRolePolicy: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
              resources: [`arn:${Aws.PARTITION}:logs:${Aws.REGION}:${Aws.ACCOUNT_ID}:log-group:/aws/lambda/*`],
            }),
          ],
        }),
      },
    });
    (waitRole.node.defaultChild as iam.CfnRole).cfnOptions.condition = condition;

    const waitFn = new lambda.Function(this, "WaitForGatewayFunction", {
      role: waitRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "wait_for_gateway.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "wait_for_gateway_lambda")),
      description: "Wait for RTB Fabric Gateway to be fully provisioned",
      timeout: Duration.seconds(60),
      memorySize: 128,
      architecture: lambda.Architecture.ARM_64,
      environment: {
        SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
      },
      layers: [CrHelperLayer.getOrCreate(this)],
    });
    const waitFnResource = waitFn.node.findChild("Resource") as lambda.CfnFunction;
    waitFnResource.addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });
    waitFnResource.cfnOptions.condition = condition;

    const waitCr = new CustomResource(this, "WaitForRequesterGatewayCr", {
      serviceToken: waitFn.functionArn,
      properties: { GatewayId: this.requesterGateway.attrGatewayId },
    });
    waitCr.node.addDependency(this.requesterGateway);
    (waitCr.node.defaultChild as CfnResource).cfnOptions.condition = condition;
  }
}
