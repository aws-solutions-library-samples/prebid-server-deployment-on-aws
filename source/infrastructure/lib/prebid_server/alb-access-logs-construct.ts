import { PowertoolsLayer, CrHelperLayer, pythonAssetCode } from "../shared/lambda-helpers";
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, CfnMapping, CustomResource, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";
import * as path from "path";

export class AlbAccessLogsConstruct extends Construct {
  public readonly albAccessLogsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, albArn: string) {
    super(scope, id);

    this.albAccessLogsBucket = new s3.Bucket(this, "AlbAccessLogsBucket", {
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER,
      accessControl: s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: RemovalPolicy.RETAIN,
      versioned: true,
      enforceSSL: true,
      objectLockEnabled: true,
      serverAccessLogsPrefix: "access-logs/",
    });

    const elbAccountIdTable = new CfnMapping(this, "ElbAccountIdTable", {
      mapping: {
        "us-east-1": { accountid: "127311923021" },
        "us-east-2": { accountid: "033677994240" },
        "us-west-1": { accountid: "027434742980" },
        "us-west-2": { accountid: "797873946194" },
        "eu-central-1": { accountid: "054676820928" },
        "eu-west-1": { accountid: "156460612806" },
        "eu-west-2": { accountid: "652711504416" },
        "eu-west-3": { accountid: "009996457667" },
        "eu-north-1": { accountid: "897822967062" },
        "ap-east-1": { accountid: "754344448648" },
        "ap-south-1": { accountid: "718504428378" },
        "ap-northeast-1": { accountid: "582318560864" },
        "ap-northeast-2": { accountid: "600734575887" },
        "ap-northeast-3": { accountid: "383597477331" },
        "ap-southeast-1": { accountid: "114774131450" },
        "ap-southeast-2": { accountid: "783225319266" },
        "af-south-1": { accountid: "098369216593" },
        "ca-central-1": { accountid: "985666609251" },
        "eu-south-1": { accountid: "635631232127" },
        "me-south-1": { accountid: "076674570225" },
        "sa-east-1": { accountid: "507241528517" },
      },
    });

    const elbAccountId = elbAccountIdTable.findInMap(Aws.REGION, "accountid");

    this.albAccessLogsBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [
          new iam.ServicePrincipal("logdelivery.elasticloadbalancing.amazonaws.com"),
          new iam.ArnPrincipal(`arn:aws:iam::${elbAccountId}:root`),
        ],
        actions: ["s3:PutObject"],
        resources: [`${this.albAccessLogsBucket.bucketArn}/AWSLogs/${Aws.ACCOUNT_ID}/*`],
      })
    );
    this.albAccessLogsBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("logging.s3.amazonaws.com")],
        actions: ["s3:PutObject"],
        resources: [`${this.albAccessLogsBucket.bucketArn}/access-logs/*`],
      })
    );

    const enableRole = new iam.Role(this, "EnableAccessLogsFunctionRole", {
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
    const enableFn = new lambda.Function(this, "EnableAccessLogsFunction", {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "enable_access_logs.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "enable_access_logs")),
      role: enableRole,
      description: "Lambda function for enabling access logs for alb",
      timeout: Duration.minutes(1),
      memorySize: 128,
      architecture: lambda.Architecture.ARM_64,
      environment: { SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "", SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "" },
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this)],
    });
    (enableFn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });

    const enablePolicy = new iam.Policy(this, "EnableAccessLogsPolicy", {
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["elasticloadbalancing:ModifyLoadBalancerAttributes", "elasticloadbalancing:DescribeLoadBalancerAttributes"],
          resources: [albArn],
        }),
      ],
    });
    enableFn.role!.attachInlinePolicy(enablePolicy);

    enableFn.node.addDependency(enablePolicy);

    const cr = new CustomResource(this, "EnableAccessLogsCr", {
      serviceToken: enableFn.functionArn,
      properties: { ALB_ARN: albArn, ALB_LOG_BUCKET: this.albAccessLogsBucket.bucketName },
    });
    cr.node.addDependency(this.albAccessLogsBucket);
    cr.node.addDependency(enablePolicy);
    const bucketPolicy = this.albAccessLogsBucket.node.tryFindChild("Policy");
    if (bucketPolicy) cr.node.addDependency(bucketPolicy);
  }
}
