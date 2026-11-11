// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as cloudtrail from "aws-cdk-lib/aws-cloudtrail";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

export class CloudTrailConstruct extends Construct {
  public readonly trail: cloudtrail.Trail;

  constructor(scope: Construct, id: string, s3Buckets: s3.IBucket[]) {
    super(scope, id);

    const loggingBucketKey = new kms.Key(this, "CloudtrailLoggingBucketKey", {
      description: "Cloudtrail Logging Bucket Key",
      enableKeyRotation: true,
      pendingWindow: Duration.days(30),
      removalPolicy: RemovalPolicy.RETAIN,
    });

    loggingBucketKey.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "Allow access to CloudTrailLoggingBucketKey",
        principals: [
          new iam.ServicePrincipal("cloudtrail.amazonaws.com"),
          new iam.ServicePrincipal("delivery.logs.amazonaws.com"),
        ],
        effect: iam.Effect.ALLOW,
        actions: ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:CreateGrant", "kms:DescribeKey"],
        resources: ["*"],
        conditions: { StringEquals: { "aws:SourceAccount": [Aws.ACCOUNT_ID] } },
      })
    );

    const loggingBucket = new s3.Bucket(this, "CloudTrailLoggingBucket", {
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER,
      accessControl: s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryptionKey: loggingBucketKey,
      removalPolicy: RemovalPolicy.RETAIN,
      versioned: true,
      enforceSSL: true,
      objectLockEnabled: true,
      serverAccessLogsPrefix: "access-logs/",
    });

    loggingBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("logging.s3.amazonaws.com")],
        actions: ["s3:PutObject"],
        resources: [`${loggingBucket.bucketArn}/access-logs/*`],
      })
    );

    this.trail = new cloudtrail.Trail(this, "S3AndLambdaTrail", {
      bucket: loggingBucket,
      isMultiRegionTrail: false,
      includeGlobalServiceEvents: false,
      managementEvents: cloudtrail.ReadWriteType.ALL,
    });

    this.trail.addS3EventSelector(s3Buckets.map(bucket => ({ bucket })));

    this.trail.node.addDependency(loggingBucket);
  }
}
