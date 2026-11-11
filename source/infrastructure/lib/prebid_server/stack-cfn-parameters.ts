// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { CfnCondition, CfnParameter, Fn, Stack } from "aws-cdk-lib";
import * as constants from "../shared/stack-constants";

const ECS_AUTOSCALING_GROUP_NAME = "ECS Service Autoscaling Settings";
const CDN_GROUP_NAME = "Content Delivery Network (CDN) Settings";
const CONTAINER_GROUP_NAME = "Container Settings";
const LOG_ANALYTICS_GROUP_NAME = "Log Analytics Settings";
const RTB_FABRIC_GROUP_NAME = "RTB Fabric Settings";
const VPC_PEERING_GROUP_NAME = "VPC Peering Settings (Fallback)";

/**
 * StackParams — declares every deploy-time CloudFormation parameter for
 * PrebidServerStack plus the CfnConditions derived directly from those
 * parameters. Ported from the Mainline `stack_cfn_parameters.py` (the landed
 * CFN-parameter migration).
 *
 * The connectivity/log-analytics configuration is deploy-time
 * (CloudFormation parameters), not build-time (CDK context). Two mutually
 * exclusive connectivity models are supported:
 *   - RTB Fabric (primary): the Requester Gateway is created when
 *     `EnableRtbRequesterGateway=true`. The simulator Fabric Link is created and
 *     managed *externally* by `deployment/simulator_fabric_link.py` (not in CDK),
 *     so there is no in-CDK Fabric Link / Accept Lambda and no
 *     `SimulatorResponderGatewayId` parameter on this stack.
 *   - VPC peering (fallback): driven by the `Simulator*` parameters, gated by
 *     `UseVpcPeering`.
 */
export class StackParams {
  // Existing (pre-migration) parameters.
  public readonly deployCloudFrontAndWafParam: CfnParameter;
  public readonly sslCertificateParam: CfnParameter;
  public readonly ecsTaskMinCapacity: CfnParameter;
  public readonly ecsTaskMaxCapacity: CfnParameter;
  public readonly requestCountThreshold: CfnParameter;
  public readonly spotInstanceWeight: CfnParameter;

  // CFN-parameter migration parameters.
  public readonly containerImageParam: CfnParameter;
  public readonly enableLogAnalyticsParam: CfnParameter;
  public readonly enableRtbRequesterGatewayParam: CfnParameter;
  public readonly simulatorVpcIdParam: CfnParameter;
  public readonly simulatorAlbSgIdParam: CfnParameter;
  public readonly simulatorRouteTableId1Param: CfnParameter;
  public readonly simulatorRouteTableId2Param: CfnParameter;
  public readonly simulatorEndpointParam: CfnParameter;

  // CfnConditions derived from the parameters above.
  public readonly hasRtbRequesterGateway: CfnCondition;
  public readonly useVpcPeering: CfnCondition;
  public readonly hasSimulatorEndpoint: CfnCondition;

  private readonly parameterGroups: Array<{ Label: { default: string }; Parameters: string[] }> = [];

  // ParameterLabels: one entry per declared CfnParameter, in declaration order.
  // Mirrors Mainline's TemplateOptions._get_metadata() where the label default
  // is the parameter's logical id (label == logical id for every PSS parameter).
  private readonly parameterLabels: Record<string, { default: string }> = {};

  constructor(stack: Stack) {
    this.deployCloudFrontAndWafParam = new CfnParameter(stack, "InstallCloudFrontAndWAF", {
      description:
        'Yes - Use the CloudFront and Web Application Firewall to deliver your content. \n No - Skip CloudFront and WAF deployment and use your own content delivery network instead',
      type: "String",
      allowedValues: ["Yes", "No"],
      default: "Yes",
    });

    this.sslCertificateParam = new CfnParameter(stack, "SSLCertificateARN", {
      description:
        'The ARN of an SSL certificate in AWS Certificate Manager associated with a domain name. This field is only required if InstallCloudFrontAndWAF is set to "No".',
      type: "String",
      default: "",
      allowedPattern: "^$|^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[a-zA-Z0-9-]+$",
      constraintDescription: "Must be a valid ACM certificate ARN or empty if using CloudFront",
    });

    this.addParameterToGroup(this.deployCloudFrontAndWafParam, CDN_GROUP_NAME);
    this.addParameterToGroup(this.sslCertificateParam, CDN_GROUP_NAME);

    this.ecsTaskMinCapacity = new CfnParameter(stack, "ECSTaskMinCapacity", {
      description: "The minimum number of tasks to run for the Prebid Server ECS service",
      type: "Number",
      default: constants.TASK_MIN_CAPACITY,
      minValue: 1,
      constraintDescription: "Minimum capacity must be at least 1 task",
    });

    this.ecsTaskMaxCapacity = new CfnParameter(stack, "ECSTaskMaxCapacity", {
      description: "The maximum number of tasks to run for the Prebid Server ECS service",
      type: "Number",
      default: constants.TASK_MAX_CAPACITY,
      minValue: 1,
      constraintDescription: "Maximum capacity must be at least 1 task",
    });

    this.requestCountThreshold = new CfnParameter(stack, "RequestsPerTargetThreshold", {
      description: "The number of requests per target to trigger scaling up the Prebid Server ECS service",
      type: "Number",
      default: constants.REQUESTS_PER_TARGET_THRESHOLD,
      minValue: 100,
      maxValue: 10000,
      constraintDescription: "Requests per target threshold must be between 100 and 10000",
    });

    this.spotInstanceWeight = new CfnParameter(stack, "SpotInstanceWeight", {
      description:
        "Spot instance weight configuration (On-demand weight fixed at 1). Default Spot weight is 1, adjustable as needed",
      type: "Number",
      default: constants.SPOT_INSTANCE_WEIGHT,
      minValue: 0,
      constraintDescription: "Spot instance weight must be a non-negative number",
    });

    this.addParameterToGroup(this.ecsTaskMinCapacity, ECS_AUTOSCALING_GROUP_NAME);
    this.addParameterToGroup(this.ecsTaskMaxCapacity, ECS_AUTOSCALING_GROUP_NAME);
    this.addParameterToGroup(this.requestCountThreshold, ECS_AUTOSCALING_GROUP_NAME);
    this.addParameterToGroup(this.spotInstanceWeight, ECS_AUTOSCALING_GROUP_NAME);

    // --- Container Settings ---
    this.containerImageParam = new CfnParameter(stack, "ContainerImageUri", {
      description:
        "ECR image URI for the Prebid Server container. Leave empty to build from source (CDK deployment path). Required when deploying via synthesized CloudFormation template.",
      type: "String",
      default: "",
    });
    this.addParameterToGroup(this.containerImageParam, CONTAINER_GROUP_NAME);

    // --- Log Analytics Settings ---
    this.enableLogAnalyticsParam = new CfnParameter(stack, "EnableLogAnalytics", {
      description:
        "Enable log analytics for Prebid Server auction data (EFS \u2192 DataSync \u2192 S3 \u2192 Glue ETL \u2192 Athena)",
      type: "String",
      allowedValues: ["true", "false"],
      default: "false",
    });
    this.addParameterToGroup(this.enableLogAnalyticsParam, LOG_ANALYTICS_GROUP_NAME);

    // --- RTB Fabric Settings ---
    this.enableRtbRequesterGatewayParam = new CfnParameter(stack, "EnableRtbRequesterGateway", {
      description:
        "Create an RTB Fabric Requester Gateway for partner connectivity. Set to 'true' to provision the gateway. Fabric Link lifecycle is managed by the simulator_fabric_link.py script.",
      type: "String",
      allowedValues: ["true", "false"],
      default: "false",
    });
    this.addParameterToGroup(this.enableRtbRequesterGatewayParam, RTB_FABRIC_GROUP_NAME);

    // --- VPC Peering Settings (Fallback) ---
    this.simulatorVpcIdParam = new CfnParameter(stack, "SimulatorVpcId", {
      description:
        "The VPC ID of the BidderSimulatorStack. Required for VPC peering connectivity (fallback when RTB Fabric is not available).",
      type: "String",
      default: "",
    });
    this.simulatorAlbSgIdParam = new CfnParameter(stack, "SimulatorAlbSgId", {
      description:
        "The ALB Security Group ID from the BidderSimulatorStack. Used to allow traffic from PrebidServerStack VPC over VPC peering.",
      type: "String",
      default: "",
    });
    this.simulatorRouteTableId1Param = new CfnParameter(stack, "SimulatorRouteTableId1", {
      description:
        "First private subnet route table ID from the BidderSimulatorStack VPC. Used for return traffic routing over VPC peering.",
      type: "String",
      default: "",
    });
    this.simulatorRouteTableId2Param = new CfnParameter(stack, "SimulatorRouteTableId2", {
      description:
        "Second private subnet route table ID from the BidderSimulatorStack VPC. Used for return traffic routing over VPC peering.",
      type: "String",
      default: "",
    });
    this.simulatorEndpointParam = new CfnParameter(stack, "SimulatorEndpoint", {
      description:
        "The bidder simulator's internal ALB DNS name. Used as the ECS bidder endpoint when VPC peering is the connectivity model.",
      type: "String",
      default: "",
    });

    this.addParameterToGroup(this.simulatorVpcIdParam, VPC_PEERING_GROUP_NAME);
    this.addParameterToGroup(this.simulatorAlbSgIdParam, VPC_PEERING_GROUP_NAME);
    this.addParameterToGroup(this.simulatorRouteTableId1Param, VPC_PEERING_GROUP_NAME);
    this.addParameterToGroup(this.simulatorRouteTableId2Param, VPC_PEERING_GROUP_NAME);
    this.addParameterToGroup(this.simulatorEndpointParam, VPC_PEERING_GROUP_NAME);

    // --- CfnConditions ---
    // HasRtbRequesterGateway: EnableRtbRequesterGateway == "true"
    this.hasRtbRequesterGateway = new CfnCondition(stack, "HasRtbRequesterGateway", {
      expression: Fn.conditionEquals(this.enableRtbRequesterGatewayParam.valueAsString, "true"),
    });

    // UseVpcPeering: SimulatorVpcId != ""
    this.useVpcPeering = new CfnCondition(stack, "UseVpcPeering", {
      expression: Fn.conditionNot(Fn.conditionEquals(this.simulatorVpcIdParam.valueAsString, "")),
    });

    // HasSimulatorEndpoint: SimulatorEndpoint != ""
    this.hasSimulatorEndpoint = new CfnCondition(stack, "HasSimulatorEndpoint", {
      expression: Fn.conditionNot(Fn.conditionEquals(this.simulatorEndpointParam.valueAsString, "")),
    });

    // Register the parameter groups on the stack's CloudFormation Interface metadata.
    this.registerParameterGroups(stack);
  }

  private addParameterToGroup(param: CfnParameter, groupLabel: string): void {
    const logicalId = param.node.id;
    const existing = this.parameterGroups.find((g) => g.Label.default === groupLabel);
    if (existing) {
      existing.Parameters.push(logicalId);
    } else {
      this.parameterGroups.push({ Label: { default: groupLabel }, Parameters: [logicalId] });
    }
    // Record the ParameterLabels entry (label default == logical id), matching
    // Mainline. Every parameter added to a group also gets a label entry.
    this.parameterLabels[logicalId] = { default: logicalId };
  }

  private registerParameterGroups(stack: Stack): void {
    // Merge the CloudFormation Interface metadata into whatever the base
    // SolutionStack constructor already stamped (the three aws:solutions:*
    // keys), rather than replacing stack.templateOptions.metadata wholesale.
    // Setting the property outright here would clobber those keys.
    const metadata = (stack.templateOptions.metadata =
      stack.templateOptions.metadata ?? {}) as Record<string, unknown>;
    metadata["AWS::CloudFormation::Interface"] = {
      ParameterGroups: this.parameterGroups,
      ParameterLabels: this.parameterLabels,
    };
  }
}
