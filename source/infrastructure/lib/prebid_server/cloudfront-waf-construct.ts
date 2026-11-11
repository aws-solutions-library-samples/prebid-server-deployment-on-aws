import { PowertoolsLayer, CrHelperLayer, pythonAssetCode } from "../shared/lambda-helpers";
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, CfnOutput, CustomResource, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as origins from "aws-cdk-lib/aws-cloudfront-origins";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";
import * as path from "path";

export class CloudFrontWafConstruct extends Construct {
  public readonly prebidCloudFrontDistribution: cloudfront.Distribution;
  public readonly wafWebaclName: string;
  public readonly prefixListId: string;

  constructor(scope: Construct, id: string, prebidAlb: elbv2.ApplicationLoadBalancer, xHeaderSecretValue: string) {
    super(scope, id);

    // CloudFront access logs bucket
    const cfLogsBucketKey = new kms.Key(this, "CloudFrontAccessLogsBucketKey", {
      description: "CloudFront Access Logging Bucket Key",
      enableKeyRotation: true,
      pendingWindow: Duration.days(30),
      removalPolicy: RemovalPolicy.RETAIN,
    });
    cfLogsBucketKey.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal("delivery.logs.amazonaws.com")],
        effect: iam.Effect.ALLOW,
        actions: ["kms:GenerateDataKey*", "kms:Decrypt"],
        resources: ["*"],
        conditions: { StringEquals: { "aws:SourceAccount": [Aws.ACCOUNT_ID] } },
      })
    );

    const cfLogsBucket = new s3.Bucket(this, "CloudFrontAccessLogsBucket", {
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER,
      encryptionKey: cfLogsBucketKey,
      accessControl: s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: RemovalPolicy.RETAIN,
      versioned: true,
      enforceSSL: true,
      objectLockEnabled: true,
    });
    (cfLogsBucket.node.defaultChild as s3.CfnBucket).addMetadata("guard", { SuppressedRules: ["S3_BUCKET_LOGGING_ENABLED"] });
    // Backward compat: maintain logical ID from v1.0.x (matches Python)
    (cfLogsBucket.node.defaultChild as s3.CfnBucket).overrideLogicalId("CloudFrontAccessLogsBucket337A74EE");

    // Prefix list ID custom resource
    const getPrefixIdFunctionRole = new iam.Role(this, "GetPrefixIdFunctionRole", {
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
    const getPrefixIdFn = new lambda.Function(this, "GetPrefixIdFunction", {
      role: getPrefixIdFunctionRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "get_prefix_id.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "prefix_id_lambda")),
      description: "Lambda function for getting prefix list ID",
      timeout: Duration.minutes(1),
      memorySize: 256,
      architecture: lambda.Architecture.ARM_64,
      environment: { SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "", SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "" },
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this)],
    });
    (getPrefixIdFn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });
    const getPrefixIdPolicy = new iam.Policy(this, "GetPrefixIdFunctionPolicy", {
      statements: [new iam.PolicyStatement({ actions: ["ec2:DescribeManagedPrefixLists"], resources: ["*"] })],
    });
    getPrefixIdFn.role!.attachInlinePolicy(getPrefixIdPolicy);
    getPrefixIdFn.node.addDependency(getPrefixIdPolicy);
    const prefixIdCr = new CustomResource(this, "GetPrefixIdCr", { serviceToken: getPrefixIdFn.functionArn });
    prefixIdCr.node.addDependency(getPrefixIdFn);
    this.prefixListId = prefixIdCr.getAttString("prefix_list_id");

    // WAF WebACL custom resource
    const wafPolicy = new iam.Policy(this, "WafWebAclFunctionWafPolicy", {
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["wafv2:CreateWebACL", "wafv2:DeleteWebACL", "wafv2:UpdateWebACL"],
          resources: [
            `arn:aws:wafv2:us-east-1:${Aws.ACCOUNT_ID}:global/webacl/PrebidWaf-*`,
            `arn:aws:wafv2:us-east-1:${Aws.ACCOUNT_ID}:global/managedruleset/*/*`,
          ],
        }),
      ],
    });

    const createWafWebAclFunctionRole = new iam.Role(this, "CreateWafWebAclFunctionRole", {
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
    const createWafFn = new lambda.Function(this, "CreateWafWebAclFunction", {
      role: createWafWebAclFunctionRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "create_waf_webacl.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "waf_webacl_lambda")),
      description: "Lambda function for creating Waf Web Acl",
      timeout: Duration.minutes(1),
      memorySize: 256,
      architecture: lambda.Architecture.ARM_64,
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this)],
      environment: {
        SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
        SOLUTION_APPLICATION_TYPE: constants.SOLUTION_APPLICATION_TYPE,
        SOLUTION_NAME: this.node.tryGetContext("SOLUTION_NAME") ?? "",
      },
    });
    (createWafFn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });
    createWafFn.role!.attachInlinePolicy(wafPolicy);
    createWafFn.node.addDependency(wafPolicy);

    const wafCr = new CustomResource(this, "WafWebAclCr", { serviceToken: createWafFn.functionArn });
    wafCr.node.addDependency(createWafFn);
    const wafWebaclArn = wafCr.getAttString("webacl_arn");
    this.wafWebaclName = wafCr.getAttString("webacl_name");

    // CloudFront distribution
    const origin = new origins.LoadBalancerV2Origin(prebidAlb, {
      protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
      customHeaders: { [constants.X_SECRET_HEADER_NAME]: xHeaderSecretValue },
    });

    const responseHeadersPolicy = cloudfront.ResponseHeadersPolicy.fromResponseHeadersPolicyId(
      this, "CloudFrontResponseHeadersPolicy", constants.RESPONSE_HEADERS_POLICY_ID
    );

    const cachePolicy = new cloudfront.CachePolicy(this, "CustomCachePolicy", {
      cachePolicyName: `${Aws.STACK_NAME}CachePolicy-${Aws.REGION}`,
      comment: "Cache policy for /cache* paths with uuid query string and origin header",
      queryStringBehavior: cloudfront.CacheQueryStringBehavior.allowList("uuid"),
      enableAcceptEncodingGzip: true,
      enableAcceptEncodingBrotli: true,
    });

    const healthCachePolicy = new cloudfront.CachePolicy(this, "HealthCachePolicy", {
      cachePolicyName: `${Aws.STACK_NAME}HealthCachePolicy-${Aws.REGION}`,
      comment: "No cache policy for /cache/health path",
      defaultTtl: Duration.seconds(30),
      minTtl: Duration.seconds(30),
      maxTtl: Duration.seconds(30),
    });

    this.prebidCloudFrontDistribution = new cloudfront.Distribution(this, "PrebidCloudFrontDist", {
      comment: "Guidance for Deploying a Prebid Server on AWS",
      defaultBehavior: {
        origin,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
        responseHeadersPolicy,
      },
      additionalBehaviors: {
        "/cache/health": { origin, allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD, cachePolicy: healthCachePolicy, responseHeadersPolicy, originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER },
        "/cache*": { origin, allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL, cachePolicy, responseHeadersPolicy, originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER },
      },
      webAclId: wafWebaclArn,
      enableLogging: true,
      logBucket: cfLogsBucket,
    });
    (this.prebidCloudFrontDistribution.node.findChild("Resource") as cloudfront.CfnDistribution).addMetadata("guard", {
      SuppressedRules: ["CLOUDFRONT_MINIMUM_PROTOCOL_VERSION_RULE"],
    });

    // Delete WAF WebACL custom resource
    const cfPolicy = new iam.Policy(this, "WafWebAclFunctionCloudFrontPolicy", {
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:ListDistributions", "cloudfront:ListDistributionsByWebACLId", "cloudfront:UpdateDistribution"],
          resources: [`arn:aws:cloudfront::${Aws.ACCOUNT_ID}:distribution/${this.prebidCloudFrontDistribution.distributionId}`],
        }),
        new iam.PolicyStatement({ effect: iam.Effect.ALLOW, actions: ["cloudwatch:ListMetrics", "cloudwatch:GetMetricStatistics", "ec2:DescribeRegions"], resources: ["*"] }),
      ],
    });
    createWafFn.role!.attachInlinePolicy(cfPolicy);

    const delWafWebAclFunctionRole = new iam.Role(this, "DelWafWebAclFunctionRole", {
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
    const delWafFn = new lambda.Function(this, "DelWafWebAclFunction", {
      role: delWafWebAclFunctionRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "delete_waf_webacl.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "waf_webacl_lambda")),
      description: "Lambda function for deleting Waf Web Acl",
      timeout: Duration.minutes(1),
      memorySize: 256,
      architecture: lambda.Architecture.ARM_64,
      environment: { SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "", SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "" },
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this)],
    });
    (delWafFn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });
    delWafFn.role!.attachInlinePolicy(wafPolicy);
    delWafFn.role!.attachInlinePolicy(cfPolicy);
    delWafFn.node.addDependency(wafPolicy);
    delWafFn.node.addDependency(cfPolicy);

    new CustomResource(this, "DeleteWafWebAclCr", {
      serviceToken: delWafFn.functionArn,
      properties: {
        CF_DISTRIBUTION_ID: this.prebidCloudFrontDistribution.distributionId,
        WAF_WEBACL_NAME: this.wafWebaclName,
        WAF_WEBACL_ID: wafCr.getAttString("webacl_id"),
        WAF_WEBACL_LOCKTOKEN: wafCr.getAttString("webacl_locktoken"),
      },
    });
  }
}
