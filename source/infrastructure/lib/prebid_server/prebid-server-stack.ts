// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  Aws, CfnCondition, CfnOutput, CustomResource, Duration, Fn,
  RemovalPolicy, Stack, StackProps,
} from "aws-cdk-lib";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import { StackParams } from "./stack-cfn-parameters";
import { ContainerImageConstruct } from "./container-image-construct";
import { ArtifactsManager } from "./artifacts-construct";
import { VpcConstruct } from "./vpc-construct";
import { RtbFabricConstruct } from "./rtb-fabric-construct";
import { VpcPeeringConstruct } from "./vpc-peering-construct";
import { DataSyncMonitoring } from "./datasync-constructs";
import { GlueEtl } from "./glue-constructs";
import { CloudTrailConstruct } from "./cloudtrail-construct";
import { CacheConstruct } from "./cache-construct";
import { OperationalMetricsConstruct } from "./operational-metrics-construct";
import { CloudFrontEntryDeployment } from "./cloudfront-entry-deployment";
import { ALBEntryDeployment } from "./alb-entry-deployment";
import { PowertoolsLayer, CrHelperLayer, pythonAssetCode } from "../shared/lambda-helpers";
import * as constants from "../shared/stack-constants";
import { isContextTrue } from "../shared/stack-constants";
import * as path from "path";

import { SolutionStack } from "../shared/solution-stack";

export type PrebidServerStackProps = StackProps;

export class PrebidServerStack extends SolutionStack {
  public static readonly STACK_NAME = "prebid-server-deployment-on-aws";
  public static readonly DESCRIPTION = "Guidance for Deploying a Prebid Server on AWS";

  constructor(scope: Construct, id: string, props: PrebidServerStackProps = {}) {
    super(scope, id, {
      ...props,
      description: PrebidServerStack.DESCRIPTION,
      templateFilename: "prebid-server-deployment-on-aws.template",
    });

    const stackParams = new StackParams(this);

    const deployCloudFrontCondition = new CfnCondition(this, "DeployCloudFrontWafCondition", {
      expression: Fn.conditionEquals(stackParams.deployCloudFrontAndWafParam.valueAsString, "Yes"),
    });
    const deployAlbHttpsCondition = new CfnCondition(this, "DeployALBHttpsCondition", {
      expression: Fn.conditionEquals(stackParams.deployCloudFrontAndWafParam.valueAsString, "No"),
    });

    // Stored requests bucket
    const accessLogsBucket = this.createAccessLogsBucket();
    const storedRequestsBucket = this.createStoredRequestsBucket(accessLogsBucket);

    // Whether the bidder simulator is synthesized is a build-time decision read
    // from CDK context (deploy.sh always passes --context deployBiddingSimulator=true
    // when building with the simulator). All runtime connectivity configuration is
    // supplied via CloudFormation parameters, not cross-stack references.
    const deployBiddingSimulator = isContextTrue(this.node.tryGetContext("deployBiddingSimulator"));

    // Container image
    const containerImage = new ContainerImageConstruct(this, "ContainerImage", storedRequestsBucket, deployBiddingSimulator);

    // Artifacts
    const artifacts = new ArtifactsManager(this, "Artifacts");

    // VPC
    const vpc = new VpcConstruct(this, "VPC", artifacts.artifactsBucket, containerImage.dockerConfigsBucket, storedRequestsBucket);

    // Always create the RTB Fabric construct — resources are gated by CfnConditions.
    new RtbFabricConstruct(this, "RtbFabric", vpc, stackParams);

    // Always create the VPC Peering construct — resources are gated by UseVpcPeering.
    new VpcPeeringConstruct(this, "VpcPeering", vpc, stackParams);

    // ECS Cluster
    const prebidCluster = new ecs.Cluster(this, "PrebidCluster", { vpc: vpc.prebidVpc, containerInsights: true });

    // ECS Cluster output (consumed by deployment/simulator_fabric_link.py).
    // This output is created on the stack scope, so its logical ID is already the flat
    // "EcsClusterName". Mainline pins it explicitly (CfnOutput(self, "EcsClusterName",
    // key="EcsClusterName", ...)); add the override for determinism and mainline parity.
    const ecsClusterNameOutput = new CfnOutput(this, "EcsClusterName", {
      value: prebidCluster.clusterName,
      description: "ECS Cluster Name",
    });
    ecsClusterNameOutput.overrideLogicalId("EcsClusterName");

    // DataSync monitoring
    const datasyncMonitor = new DataSyncMonitoring(this, "DataSyncMonitor");

    // Operational Metrics
    const opMetrics = new OperationalMetricsConstruct(this, "operational-metrics");

    // Glue ETL
    const glueEtl = new GlueEtl(this, "MetricsEtl", artifacts, opMetrics.operationalMetricsLayer);

    // DataSync S3 layer — used by EFS cleanup and Glue trigger Lambdas
    const datasyncS3Layer = new lambda.LayerVersion(this, "DataSyncS3Layer", {
      code: lambda.Code.fromAsset(path.join(constants.PKG_ROOT, "aws_lambda_layers/datasync_s3_layer/")),
      layerVersionName: `${Aws.STACK_NAME}-datasync-s3-layer`,
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
    });
    glueEtl.lambdaFunction.addLayers(datasyncS3Layer);

    // CloudTrail
    new CloudTrailConstruct(this, "CloudtrailConstruct", [
      artifacts.artifactsBucket,
      glueEtl.metricsSourceBucket,
      glueEtl.analyticsSourceBucket,
      glueEtl.outputBucket,
    ]);

    // Header secret custom resource
    const headerSecretRole = new iam.Role(this, "HeaderSecretGenFunctionRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      inlinePolicies: {
        LambdaFunctionServiceRolePolicy: new iam.PolicyDocument({
          statements: [new iam.PolicyStatement({
            actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            resources: [`arn:${Aws.PARTITION}:logs:${Aws.REGION}:${Aws.ACCOUNT_ID}:log-group:/aws/lambda/*`],
          })],
        }),
      },
    });
    const headerSecretFn = new lambda.Function(this, "HeaderSecretGenFunction", {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "header_secret_gen.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "header_secret_lambda")),
      role: headerSecretRole,
      description: "Lambda function for header secret generation",
      timeout: Duration.seconds(30),
      memorySize: 128,
      architecture: lambda.Architecture.ARM_64,
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this)],
      environment: { SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "", SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "" },
    });
    (headerSecretFn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });
    const headerSecretCr = new CustomResource(this, "HeaderSecretGenCr", { serviceToken: headerSecretFn.functionArn });
    const xHeaderSecretValue = headerSecretCr.getAttString("header_secret_value");

    new CfnOutput(this, "Header-Key", { value: xHeaderSecretValue, description: "Header Key" });

    // Cache
    const cache = new CacheConstruct(this, "CacheConstruct", vpc, opMetrics.operationalMetricsLayer);

    // CloudFront entry deployment
    new CloudFrontEntryDeployment(this, "CloudFrontEntryDeployment", {
      stackParams,
      deployCloudFrontWafCondition: deployCloudFrontCondition,
      artifactsConstruct: artifacts,
      datasyncMonitor,
      vpcConstruct: vpc,
      containerImageConstruct: containerImage,
      prebidCluster,
      glueEtl,
      cacheConstruct: cache,
      datasyncS3Layer,
      operationalMetricsLayer: opMetrics.operationalMetricsLayer,
      xHeaderSecretValue,
      storedRequestsBucket,
    });

    // ALB entry deployment
    new ALBEntryDeployment(this, "ALBEntryDeployment", {
      stackParams,
      deployAlbHttpsCondition: deployAlbHttpsCondition,
      artifactsConstruct: artifacts,
      datasyncMonitor,
      vpcConstruct: vpc,
      containerImageConstruct: containerImage,
      prebidCluster,
      glueEtl,
      cacheConstruct: cache,
      datasyncS3Layer,
      operationalMetricsLayer: opMetrics.operationalMetricsLayer,
      storedRequestsBucket,
    });
  }

  private createAccessLogsBucket(): s3.Bucket {
    const bucket = new s3.Bucket(this, "StoredRequestsAccessLogsBucket", {
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: RemovalPolicy.RETAIN,
      versioned: true,
      autoDeleteObjects: false,
      enforceSSL: true,
      lifecycleRules: [{
        id: "AccessLogsLifecycle",
        enabled: true,
        expiration: Duration.days(90),
        transitions: [{ storageClass: s3.StorageClass.INFREQUENT_ACCESS, transitionAfter: Duration.days(30) }],
        noncurrentVersionExpiration: Duration.days(30),
      }],
    });
    bucket.addToResourcePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      principals: [new iam.ServicePrincipal("logging.s3.amazonaws.com")],
      actions: ["s3:PutObject"],
      resources: [`${bucket.bucketArn}/stored-requests-bucket-logs/*`],
      conditions: { StringEquals: { "aws:SourceAccount": Aws.ACCOUNT_ID } },
    }));
    return bucket;
  }

  private createStoredRequestsBucket(accessLogsBucket: s3.Bucket): s3.Bucket {
    const bucket = new s3.Bucket(this, "Bucket", {
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: RemovalPolicy.RETAIN,
      versioned: true,
      autoDeleteObjects: false,
      enforceSSL: true,
      serverAccessLogsBucket: accessLogsBucket,
      serverAccessLogsPrefix: "stored-requests-bucket-logs/",
    });

    // Ported from prebid_server_stack.py create_stored_requests_bucket():
    // CfnOutput "PrebidStoredRequestsBucket" — S3 console URL for the stored-requests bucket.
    // No CfnCondition (matches Mainline; the stored-requests bucket is unconditional).
    new CfnOutput(this, "PrebidStoredRequestsBucket", {
      value: `https://${Aws.REGION}.console.aws.amazon.com/s3/home?region=${Aws.REGION}&bucket=${bucket.bucketName}`,
      description: "Bucket for Prebid Server stored requests",
    });

    return bucket;
  }
}
