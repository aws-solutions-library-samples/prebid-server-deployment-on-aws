// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  Aws, CfnCondition, CfnOutput, CfnParameter, Duration, Fn, RemovalPolicy, Stack, StackProps,
} from "aws-cdk-lib";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as constants from "../shared/stack-constants";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as targets from "aws-cdk-lib/aws-elasticloadbalancingv2-targets";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as rtbfabric from "aws-cdk-lib/aws-rtbfabric";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import { Construct } from "constructs";
import * as path from "path";

export class BidderSimulatorStack extends Stack {
  public readonly alb: elbv2.ApplicationLoadBalancer;
  public readonly albSecurityGroup: ec2.SecurityGroup;
  public readonly bidderVpc: ec2.Vpc;
  public readonly responderGateway: rtbfabric.CfnResponderGateway;
  public readonly privateRouteTableIds: string[];
  public readonly enableRtbFabricParam: CfnParameter;
  public readonly hasRtbFabric: CfnCondition;

  constructor(scope: Construct, id: string, props: StackProps = {}) {
    super(scope, id, props);

    // EnableRtbFabric CloudFormation parameter — controls Responder Gateway
    // creation at deploy time (replaces the build-time includeRtbFabric boolean).
    this.enableRtbFabricParam = new CfnParameter(this, "EnableRtbFabric", {
      type: "String",
      allowedValues: ["true", "false"],
      default: "true",
      description:
        "Enable RTB Fabric Responder Gateway creation. Set to 'false' for VPC peering fallback in non-RTB regions.",
    });

    // HasRtbFabric CfnCondition.
    this.hasRtbFabric = new CfnCondition(this, "HasRtbFabric", {
      expression: Fn.conditionEquals(this.enableRtbFabricParam.valueAsString, "true"),
    });

    // VPC
    this.bidderVpc = new ec2.Vpc(this, "BidderSimulatorVpc", {
      ipAddresses: ec2.IpAddresses.cidr("10.1.0.0/16"),
      maxAzs: 2,
      natGateways: 2,
      subnetConfiguration: [
        { subnetType: ec2.SubnetType.PUBLIC, name: "BidderSimulator-Public", cidrMask: 20 },
        { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, name: "BidderSimulator-Private", cidrMask: 20 },
      ],
    });

    // Demo website
    const demoBucket = new s3.Bucket(this, "DemoWebsiteBucket", {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      enforceSSL: true,
    });
    (demoBucket.node.defaultChild as s3.CfnBucket).addMetadata("guard", { SuppressedRules: ["S3_BUCKET_LOGGING_ENABLED"] });

    const demoOac = new cloudfront.S3OriginAccessControl(this, "DemoOac", {
      signing: cloudfront.Signing.SIGV4_NO_OVERRIDE,
      originAccessControlName: `DemoOac-${Aws.STACK_NAME}-${Aws.REGION}`,
      description: "OAC for demo bucket",
    });
    const demoOrigin = origins.S3BucketOrigin.withOriginAccessControl(demoBucket, { originAccessControl: demoOac });

    const demoCfDist = new cloudfront.Distribution(this, "DemoCloudFrontDist", {
      comment: "Demo website for Prebid Server on AWS",
      defaultBehavior: {
        origin: demoOrigin,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
      defaultRootObject: "index.html",
    });

    // loadtest/... assets live under the repo source root (source/loadtest),
    // NOT under the CDK package dir (source/infrastructure). Resolve against
    // SOURCE_ROOT so `cdk synth` finds them (mirrors mainline's
    // source/loadtest/demo location).
    const demoPath = path.join(constants.SOURCE_ROOT, "loadtest/demo");
    // prune=false prevents this deployment from deleting files uploaded
    // by other BucketDeployment constructs targeting the same bucket.
    new s3deploy.BucketDeployment(this, "DemoWebsiteDeployment", {
      sources: [s3deploy.Source.asset(path.join(demoPath, "dist"))],
      destinationBucket: demoBucket,
      prune: false,
      memoryLimit: 512,
    });
    new s3deploy.BucketDeployment(this, "DemoAssetsDeployment", {
      sources: [s3deploy.Source.asset(path.join(demoPath, "assets"))],
      destinationBucket: demoBucket,
      destinationKeyPrefix: "assets/",
      prune: false,
      // Task 9.6: aligned to Mainline (memory_limit=512, no ephemeral storage) so
      // both demo BucketDeployment custom resources match Mainline exactly. Lambda
      // memory affects only the deployment custom-resource behavior/cost, not the
      // deployed website content.
      memoryLimit: 512,
    });

    new CfnOutput(this, "DemoWebsiteUrl", {
      value: `https://${demoCfDist.domainName}/index.html`,
      description: "Demo website URL served via CloudFront",
    });

    // Parameters
    const delayPct = new CfnParameter(this, "bidResponseDelayPercentage", { type: "Number", minValue: 0, maxValue: 1, default: 0, description: "Percentage of bid requests to get delayed response" });
    const timeoutPct = new CfnParameter(this, "bidResponseTimeoutPercentage", { type: "Number", minValue: 0, maxValue: 1, default: 0, description: "Percentage of bid requests to get timeout response" });
    const delayProb = new CfnParameter(this, "bidResponseDelayProbability", { type: "Number", minValue: 0, maxValue: 1, default: 0, description: "Probability for a Bid Response to be delay" });
    const timeoutProb = new CfnParameter(this, "bidResponseTimeoutProbability", { type: "Number", minValue: 0, maxValue: 1, default: 0, description: "Probability for a Bid Response to be timeout" });

    // Bidder simulator Lambda
    const bidderFn = new lambda.Function(this, "bidderSimulator", {
      functionName: `${Aws.STACK_NAME}-bidding-server-simulator`,
      // loadtest/... lives under the repo source root (source/loadtest), not the
      // CDK package dir — resolve against SOURCE_ROOT (mirrors mainline).
      code: lambda.Code.fromAsset(path.join(constants.SOURCE_ROOT, "loadtest/bidder_simulator/lambdas/loadtest_bidder")),
      handler: "handler.lambda_handler",
      environment: {
        BID_RESPONSES_DELAY_PERCENTAGE: delayPct.valueAsString,
        BID_RESPONSES_TIMEOUT_PERCENTAGE: timeoutPct.valueAsString,
        A_BID_RESPONSE_DELAY_PROBABILITY: delayProb.valueAsString,
        A_BID_RESPONSE_TIMEOUT_PROBABILITY: timeoutProb.valueAsString,
        DEMO_CLOUDFRONT_DOMAIN: demoCfDist.domainName,
      },
      description: "Simulate a bidding server to send a Bid Response",
      timeout: Duration.minutes(1),
      memorySize: 256,
      architecture: lambda.Architecture.ARM_64,
      runtime: lambda.Runtime.PYTHON_3_11,
    });

    // ALB
    this.albSecurityGroup = new ec2.SecurityGroup(this, "AlbSecurityGroup", {
      vpc: this.bidderVpc,
      description: "Security group for internal bidder simulator ALB",
      allowAllOutbound: true,
    });

    const stackUuid = Fn.select(2, Fn.split("/", Aws.STACK_ID));
    const albSuffix = Fn.select(0, Fn.split("-", stackUuid));

    this.alb = new elbv2.ApplicationLoadBalancer(this, "BidderSimulatorAlb", {
      loadBalancerName: `bidder-sim-${albSuffix}`,
      vpc: this.bidderVpc,
      internetFacing: false,
      securityGroup: this.albSecurityGroup,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });

    const lambdaTg = new elbv2.ApplicationTargetGroup(this, "LambdaTargetGroup", {
      targetType: elbv2.TargetType.LAMBDA,
      targets: [new targets.LambdaTarget(bidderFn)],
      healthCheck: { enabled: true, path: "/", interval: Duration.seconds(30), timeout: Duration.seconds(5), healthyThresholdCount: 2, unhealthyThresholdCount: 2 },
    });

    this.alb.addListener("HttpListener", {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultTargetGroups: [lambdaTg],
    });

    // deploy.sh reads this by EXACT key (get_stack_output "$SIMULATOR_STACK_NAME"
    // "BidderSimulatorAlbEndpoint") on the vpc-peering path. It is a stack-scope output so its
    // logical ID is already flat; pin it explicitly for determinism / script-contract safety.
    const bssAlbEndpointOutput = new CfnOutput(this, "BidderSimulatorAlbEndpoint", {
      value: `http://${this.alb.loadBalancerDnsName}`,
      description:
        "Internal ALB endpoint URL for bidder simulator (accessible only within VPC or via VPC peering)",
    });
    bssAlbEndpointOutput.overrideLogicalId("BidderSimulatorAlbEndpoint");

    // RTB Fabric Responder Gateway — always defined; resources gated by HasRtbFabric.
    this.responderGateway = this.createResponderGateway();

    // Outputs for the two-step deploy.sh wiring (VPC peering path).
    // deploy.sh reads each of these by EXACT key (get_stack_output "$SIMULATOR_STACK_NAME" "<key>").
    // They are stack-scope outputs so logical IDs are already flat; pin explicitly for determinism.
    const bssVpcIdOutput = new CfnOutput(this, "BidderSimulatorVpcId", {
      value: this.bidderVpc.vpcId,
      description: "Bidder Simulator VPC ID for VPC peering",
    });
    bssVpcIdOutput.overrideLogicalId("BidderSimulatorVpcId");
    const bssAlbSgOutput = new CfnOutput(this, "BidderSimulatorAlbSecurityGroupId", {
      value: this.albSecurityGroup.securityGroupId,
      description: "Bidder Simulator ALB Security Group ID for VPC peering",
    });
    bssAlbSgOutput.overrideLogicalId("BidderSimulatorAlbSecurityGroupId");

    const privateSubnets = this.bidderVpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS });
    this.privateRouteTableIds = privateSubnets.subnets.map((s) => s.routeTable.routeTableId);

    const bssRt1Output = new CfnOutput(this, "BidderSimulatorRouteTableId1", {
      value: this.privateRouteTableIds.length > 0 ? this.privateRouteTableIds[0] : "",
      description: "First private subnet route table ID from BidderSimulatorStack",
    });
    bssRt1Output.overrideLogicalId("BidderSimulatorRouteTableId1");
    const bssRt2Output = new CfnOutput(this, "BidderSimulatorRouteTableId2", {
      value: this.privateRouteTableIds.length > 1 ? this.privateRouteTableIds[1] : "",
      description: "Second private subnet route table ID from BidderSimulatorStack",
    });
    bssRt2Output.overrideLogicalId("BidderSimulatorRouteTableId2");
  }

  /**
   * Create the RTB Fabric Responder Gateway (conditional on HasRtbFabric).
   * All resources are gated by the HasRtbFabric CfnCondition.
   */
  private createResponderGateway(): rtbfabric.CfnResponderGateway {
    const condition = this.hasRtbFabric;

    const responderSg = new ec2.SecurityGroup(this, "ResponderGatewaySecurityGroup", {
      vpc: this.bidderVpc,
      description: "Security group for RTB Fabric Responder Gateway",
      allowAllOutbound: true,
    });
    (responderSg.node.defaultChild as ec2.CfnSecurityGroup).cfnOptions.condition = condition;
    responderSg.addIngressRule(
      ec2.Peer.ipv4(this.bidderVpc.vpcCidrBlock),
      ec2.Port.tcp(80),
      "Allow HTTP from RTB Fabric network"
    );

    // Allow HTTP (80) from the Responder Gateway to the ALB (standalone,
    // conditional ingress rule rather than an addIngressRule on the ALB SG).
    const albIngressFromGw = new ec2.CfnSecurityGroupIngress(this, "AlbIngressFromResponderGw", {
      groupId: this.albSecurityGroup.securityGroupId,
      sourceSecurityGroupId: responderSg.securityGroupId,
      ipProtocol: "tcp",
      fromPort: 80,
      toPort: 80,
      description: "Allow HTTP from RTB Fabric Responder Gateway",
    });
    albIngressFromGw.cfnOptions.condition = condition;

    const privateSubnets = this.bidderVpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS });

    const responderGateway = new rtbfabric.CfnResponderGateway(this, "ResponderGateway", {
      port: 80,
      protocol: "HTTP",
      vpcId: this.bidderVpc.vpcId,
      subnetIds: [privateSubnets.subnets[0].subnetId],
      securityGroupIds: [responderSg.securityGroupId],
      description: "RTB Fabric Responder Gateway for bidder simulator",
      domainName: this.alb.loadBalancerDnsName,
      tags: [{ key: "Name", value: `${Aws.STACK_NAME}-BidderSimulator-ResponderGateway` }],
    });
    responderGateway.cfnOptions.condition = condition;

    const gatewayIdOutput = new CfnOutput(this, "ResponderGatewayId", {
      value: responderGateway.attrGatewayId,
      description: "RTB Fabric Responder Gateway ID",
    });
    gatewayIdOutput.condition = condition;
    // deploy.sh reads this by EXACT key (get_stack_output "$SIMULATOR_STACK_NAME" "ResponderGatewayId")
    // on the rtb-fabric path, then passes it to simulator-fabric-link.sh --responder-gateway-id.
    // Stack-scope output so already flat; pin explicitly for determinism (override is compatible
    // with the conditional output above).
    gatewayIdOutput.overrideLogicalId("ResponderGatewayId");

    const gatewayArnOutput = new CfnOutput(this, "ResponderGatewayArn", {
      value: responderGateway.attrArn,
      description: "RTB Fabric Responder Gateway ARN",
    });
    gatewayArnOutput.condition = condition;

    return responderGateway;
  }
}
