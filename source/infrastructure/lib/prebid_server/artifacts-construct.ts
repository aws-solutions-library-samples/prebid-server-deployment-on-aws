import { PowertoolsLayer, CrHelperLayer, pythonAssetCode } from "../shared/lambda-helpers";
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, CustomResource, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";
import * as path from "path";
import { randomUUID } from "crypto";

export class ArtifactsManager extends Construct {
  public readonly artifactsBucket: s3.Bucket;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    const bucketKey = new kms.Key(this, "BucketKey", {
      description: "Artifact Bucket Key",
      enableKeyRotation: true,
      pendingWindow: Duration.days(30),
      removalPolicy: RemovalPolicy.DESTROY,
    });
    bucketKey.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "Allow access to ArtifactBucket",
        principals: [
          new iam.ServicePrincipal("s3.amazonaws.com"),
          new iam.ServicePrincipal("lambda.amazonaws.com"),
          new iam.ServicePrincipal("glue.amazonaws.com"),
        ],
        effect: iam.Effect.ALLOW,
        actions: ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:CreateGrant", "kms:DescribeKey"],
        resources: ["*"],
        conditions: { StringEquals: { "aws:SourceAccount": [Aws.ACCOUNT_ID] } },
      })
    );

    this.artifactsBucket = new s3.Bucket(this, "Bucket", {
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER,
      accessControl: s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryptionKey: bucketKey,
      removalPolicy: RemovalPolicy.DESTROY,
      versioned: false,
      autoDeleteObjects: true,
      enforceSSL: true,
    });
    this.artifactsBucket.addLifecycleRule({ expiration: Duration.days(constants.DATASYNC_REPORT_LIFECYCLE_DAYS), prefix: "datasync" });
    this.artifactsBucket.addLifecycleRule({ expiration: Duration.days(constants.GLUE_ATHENA_OUTPUT_LIFECYCLE_DAYS), prefix: "athena" });
    (this.artifactsBucket.node.findChild("Resource") as s3.CfnBucket).addMetadata("guard", { SuppressedRules: ["S3_BUCKET_LOGGING_ENABLED"] });

    // Upload artifacts Lambda
    const crRole = new iam.Role(this, "CrRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      inlinePolicies: {
        LambdaCrLoggingPolicy: new iam.PolicyDocument({
          statements: [new iam.PolicyStatement({
            actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            resources: [`arn:${Aws.PARTITION}:logs:${Aws.REGION}:${Aws.ACCOUNT_ID}:log-group:/aws/lambda/*`],
          })],
        }),
        LambdaCrS3Policy: new iam.PolicyDocument({
          statements: [new iam.PolicyStatement({
            actions: ["s3:DeleteObject", "s3:GetObject", "s3:PutObject", "s3:ListBucket"],
            resources: [this.artifactsBucket.bucketArn, `${this.artifactsBucket.bucketArn}/*`],
            conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } },
          })],
        }),
      },
    });
    bucketKey.grantEncryptDecrypt(crRole);

    const uploadFn = new lambda.Function(this, "CrFunction", {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "upload_files.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "artifacts_bucket_lambda")),
      role: crRole,
      description: "Lambda function for uploading Solution artifacts to S3",
      memorySize: 256,
      timeout: Duration.minutes(1),
      architecture: lambda.Architecture.ARM_64,
      environment: { SOLUTION_ID: scope.node.tryGetContext("SOLUTION_ID") ?? "", SOLUTION_VERSION: scope.node.tryGetContext("SOLUTION_VERSION") ?? "" },
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this)],
    });
    (uploadFn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });

    const uploadCr = new CustomResource(this, "UploadArtifactsCr", {
      serviceToken: uploadFn.functionArn,
      // Bound how long CloudFormation waits on this custom resource. Without it, a
      // stuck custom-resource Lambda leaves the stack waiting on the default ~1h
      // timeout, which stalls deployments and rollbacks. This is just an artifact
      // upload, so a 5-minute ceiling is ample.
      serviceTimeout: Duration.minutes(5),
      properties: {
        artifacts_bucket_name: this.artifactsBucket.bucketName,
        custom_resource_uuid: randomUUID(),
      },
    });
    uploadCr.node.addDependency(uploadFn);
  }
}
