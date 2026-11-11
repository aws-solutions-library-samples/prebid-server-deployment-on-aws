import { redisLayerCode, SolutionsLayer, pythonAssetCode } from "../shared/lambda-helpers";
import * as constants from "../shared/stack-constants";
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, CfnOutput, CustomResource, Duration, Fn, RemovalPolicy } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as elasticache from "aws-cdk-lib/aws-elasticache";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as targets from "aws-cdk-lib/aws-elasticloadbalancingv2-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";
import { VpcConstruct } from "./vpc-construct";
import * as path from "path";

export class CacheConstruct extends Construct {
  public readonly serverlessCache: elasticache.CfnServerlessCache;
  public readonly cacheLambdaFunction: lambda.Function;
  public readonly lambdaTargetExternalCf: elbv2.ApplicationTargetGroup;
  public readonly lambdaTargetExternalAlb: elbv2.ApplicationTargetGroup;
  public readonly lambdaTargetInternalCf: elbv2.ApplicationTargetGroup;
  public readonly lambdaTargetInternalAlb: elbv2.ApplicationTargetGroup;

  constructor(scope: Construct, id: string, vpcConstruct: VpcConstruct, operationalMetricsLayer: lambda.ILayerVersion) {
    super(scope, id);

    const cacheSg = new ec2.SecurityGroup(this, "CacheSecurityGroup", {
      vpc: vpcConstruct.prebidVpc,
      description: "Security group for ElasticCache",
      allowAllOutbound: true,
    });
    (cacheSg.node.findChild("Resource") as ec2.CfnSecurityGroup).addMetadata("guard", {
      SuppressedRules: ["EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE", "SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE"],
    });

    const cacheName = Fn.join("-", ["cache", Fn.select(0, Fn.split("-", Fn.select(2, Fn.split("/", Aws.STACK_ID))))]);
    const cacheIamUserName = cacheName + "user-01";

    this.serverlessCache = new elasticache.CfnServerlessCache(this, "ServerlessCache", {
      engine: "valkey",
      majorEngineVersion: "8",
      serverlessCacheName: cacheName,
      description: `Serverless Cache for ${Aws.STACK_NAME}`,
      securityGroupIds: [cacheSg.securityGroupId],
      subnetIds: vpcConstruct.prebidVpc.privateSubnets.map((s) => s.subnetId),
    });

    const defaultUser = new elasticache.CfnUser(this, "DefaultUser", {
      userId: `${cacheName}-defaultuser-disabled`,
      userName: "default",
      engine: "valkey",
      authenticationMode: { Type: "password", Passwords: ["disabled-password-123"] },
      accessString: "off +get ~keys*",
    });

    const cacheUser = new elasticache.CfnUser(this, "CacheIAMUser", {
      userId: cacheIamUserName,
      userName: cacheIamUserName,
      engine: "valkey",
      authenticationMode: { Type: "iam" },
      accessString: "on ~* +@all",
    });

    const userGroup = new elasticache.CfnUserGroup(this, "CacheUserGroup", {
      userGroupId: `${cacheName}-group-01`,
      engine: "valkey",
      userIds: [defaultUser.userId!, cacheUser.userId!],
    });

    this.serverlessCache.userGroupId = userGroup.userGroupId;
    this.serverlessCache.addDependency(userGroup);
    userGroup.addDependency(cacheUser);
    userGroup.addDependency(defaultUser);

    // Redis package layer — bundled at synth time (pip install redis cachetools
    // --no-deps into python/), matching Mainline cache_construct.py. cache_lambda/
    // ships only cache_access.py + requirements.txt (no pre-built python/), so a
    // plain fromAsset would ship the layer WITHOUT redis/cachetools and the
    // CacheHandler would crash at invoke with "No module named 'redis'".
    const redisLayer = new lambda.LayerVersion(this, "RedisLayer", {
      code: redisLayerCode(path.join(constants.PKG_ROOT, "prebid_server/cache_lambda")),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: "Redis package layer",
    });

    this.cacheLambdaFunction = new lambda.Function(this, "CacheHandler", {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "cache_access.handler",
      code: pythonAssetCode(path.join(constants.PKG_ROOT, "prebid_server/cache_lambda")),
      layers: [redisLayer, operationalMetricsLayer, SolutionsLayer.getOrCreate(this)],
      environment: {
        REDIS_ENDPOINT: this.serverlessCache.attrEndpointAddress,
        REDIS_PORT: this.serverlessCache.attrEndpointPort,
        CACHE_NAME: this.serverlessCache.serverlessCacheName,
        CACHE_USER: cacheIamUserName,
        RESOURCE_PREFIX: Aws.STACK_NAME,
        METRICS_NAMESPACE: this.node.tryGetContext("METRICS_NAMESPACE") ?? "",
        SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
      },
      architecture: lambda.Architecture.ARM_64,
      memorySize: 256,
      timeout: Duration.seconds(30),
      vpc: vpcConstruct.prebidVpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      description: "Lambda function to handle cache operations for Prebid Server",
    });
    (this.cacheLambdaFunction.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", { SuppressedRules: ["LAMBDA_CONCURRENCY_CHECK"] });

    this.cacheLambdaFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["elasticache:Connect"],
        resources: [
          `arn:aws:elasticache:${Aws.REGION}:${Aws.ACCOUNT_ID}:serverlesscache:${this.serverlessCache.serverlessCacheName}`,
          `arn:aws:elasticache:${Aws.REGION}:${Aws.ACCOUNT_ID}:user:${cacheUser.userId}`,
        ],
      })
    );

    this.cacheLambdaFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["cloudwatch:PutMetricData"],
        resources: ["*"],
        conditions: { StringEquals: { "cloudwatch:namespace": this.node.tryGetContext("METRICS_NAMESPACE") ?? "" } },
      })
    );

    cacheSg.addIngressRule(
      ec2.Peer.securityGroupId(this.cacheLambdaFunction.connections.securityGroups[0].securityGroupId),
      ec2.Port.tcp(6379),
      "Allow Lambda to access Redis Serverless cache"
    );

    // Target groups
    const healthCheck: elbv2.HealthCheck = {
      enabled: true,
      path: "/cache/health",
      healthyHttpCodes: "200",
      interval: Duration.seconds(60),
      healthyThresholdCount: 2,
      unhealthyThresholdCount: 3,
    };

    const makeTg = (tgId: string) =>
      new elbv2.ApplicationTargetGroup(this, tgId, {
        targetType: elbv2.TargetType.LAMBDA,
        targets: [new targets.LambdaTarget(this.cacheLambdaFunction)],
        healthCheck,
      });

    this.lambdaTargetExternalCf = makeTg("CacheLambdaTargetExternalCf");
    this.lambdaTargetExternalAlb = makeTg("CacheLambdaTargetExternalAlb");
    this.lambdaTargetInternalCf = makeTg("CacheLambdaTargetInternalCf");
    this.lambdaTargetInternalAlb = makeTg("CacheLambdaTargetInternalAlb");

    new CfnOutput(this, "PrebidCache", { value: this.serverlessCache.serverlessCacheName, description: "Cache Name" });
  }
}
