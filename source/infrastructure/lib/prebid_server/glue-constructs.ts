import { PowertoolsLayer, SolutionsLayer, pythonAssetCode } from "../shared/lambda-helpers";
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Glue ETL constructs: S3Location, GlueEtl
// Ported from prebid_glue_constructs.py

import { Aws, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as datasync from "aws-cdk-lib/aws-datasync";
import * as glue from "aws-cdk-lib/aws-glue";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import { ArtifactsManager } from "./artifacts-construct";
import * as constants from "../shared/stack-constants";
import * as path from "path";
import * as fs from "fs";

const DATASYNC_PRINCIPAL = new iam.ServicePrincipal("datasync.amazonaws.com");
const GLUE_PRINCIPAL = new iam.ServicePrincipal("glue.amazonaws.com");

export class S3Location extends Construct {
  public readonly s3Location: datasync.CfnLocationS3;

  constructor(scope: Construct, id: string, s3Bucket: s3.Bucket) {
    super(scope, id);

    const role = new iam.Role(this, "Role", { assumedBy: DATASYNC_PRINCIPAL });
    const s3Actions = ["s3:GetBucketLocation", "s3:ListBucketMultipartUploads", "s3:AbortMultipartUpload", "s3:DeleteObject", "s3:ListMultipartUploadParts", "s3:GetObjectTagging", "s3:PutObjectTagging", "s3:PutObject", "s3:GetObject", "s3:ListBucket"];

    const policy = new iam.Policy(this, "Policy", {
      statements: [new iam.PolicyStatement({ actions: s3Actions, resources: [s3Bucket.bucketArn, `${s3Bucket.bucketArn}/*`], conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } } })],
    });
    role.attachInlinePolicy(policy);
    s3Bucket.encryptionKey?.grantEncryptDecrypt(role);
    policy.node.addDependency(s3Bucket);

    // Bucket policy granting DataSync role access (required for DataSync location validation)
    const bucketPolicy = new s3.BucketPolicy(this, "BucketPolicy", {
      bucket: s3Bucket,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    bucketPolicy.document.addStatements(
      new iam.PolicyStatement({
        principals: [new iam.ArnPrincipal(role.roleArn)],
        actions: s3Actions,
        resources: [s3Bucket.bucketArn, `${s3Bucket.bucketArn}/*`],
        conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } },
      })
    );
    bucketPolicy.node.addDependency(s3Bucket);

    this.s3Location = new datasync.CfnLocationS3(this, "Location", {
      s3BucketArn: s3Bucket.bucketArn,
      s3Config: { bucketAccessRoleArn: role.roleArn },
    });

    // Backward compat: maintain logical ID from v1.0.x for metrics S3 location (matches Python)
    if (id === "S3Location") {
      this.s3Location.overrideLogicalId("DataSyncMetricsS3Location7EAA1172");
    }
    this.s3Location.node.addDependency(s3Bucket);
    this.s3Location.node.addDependency(bucketPolicy);
  }
}

function createEncryptedBucket(scope: Construct, id: string, keyDescription?: string): s3.Bucket {
  const key = new kms.Key(scope, `${id}Key`, {
    description: keyDescription ?? `${scope.node.id} Bucket Key`,
    enableKeyRotation: true,
    pendingWindow: Duration.days(30),
    removalPolicy: RemovalPolicy.RETAIN,
  });
  key.addToResourcePolicy(
    new iam.PolicyStatement({
      sid: `Allow access to ${scope.node.id}Bucket`,
      principals: [new iam.ServicePrincipal("s3.amazonaws.com"), DATASYNC_PRINCIPAL, GLUE_PRINCIPAL],
      effect: iam.Effect.ALLOW,
      actions: ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:CreateGrant", "kms:DescribeKey"],
      resources: ["*"],
      conditions: { StringEquals: { "aws:SourceAccount": [Aws.ACCOUNT_ID] } },
    })
  );

  const bucket = new s3.Bucket(scope, id, {
    objectOwnership: s3.ObjectOwnership.OBJECT_WRITER,
    accessControl: s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
    blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    encryptionKey: key,
    removalPolicy: RemovalPolicy.RETAIN,
    versioned: true,
    enforceSSL: true,
    objectLockEnabled: true,
  });
  (bucket.node.defaultChild as s3.CfnBucket).addMetadata("guard", { SuppressedRules: ["S3_BUCKET_LOGGING_ENABLED"] });
  return bucket;
}

export class GlueEtl extends Construct {
  public readonly GLUE_JOB_NAME: string;
  public readonly metricsSourceBucket: s3.Bucket;
  public readonly analyticsSourceBucket: s3.Bucket;
  public readonly outputBucket: s3.Bucket;
  public readonly metricsS3Location: S3Location;
  public readonly analyticsS3Location: S3Location;
  public readonly lambdaFunction: lambda.Function;

  constructor(scope: Construct, id: string, artifactsConstruct: ArtifactsManager, operationalMetricsLayer: lambda.ILayerVersion) {
    super(scope, id);

    // Glue database/job/workflow names. The database name must be all lowercase.
    // Aws.STACK_NAME can contain uppercase characters in nested stack deployments
    // (CloudFormation appends random uppercase suffixes). We use a fixed lowercase
    // prefix for the database name to avoid this issue.
    const gluePrefix = `${Aws.STACK_NAME}-${Aws.REGION}-${id.toLowerCase()}`;
    this.GLUE_JOB_NAME = `${gluePrefix}-job`;
    const glueDatabaseName = `prebid-server-${Aws.REGION}-${id.toLowerCase()}-database`;

    // Source buckets
    this.metricsSourceBucket = createEncryptedBucket(this, "DataSyncMetricsBucket");
    // Backward compat: maintain logical ID from v1.0.x (matches Python)
    this.analyticsSourceBucket = createEncryptedBucket(this, "DataSyncAnalyticsBucket");

    // S3 locations for DataSync
    this.metricsS3Location = new S3Location(this, "S3Location", this.metricsSourceBucket);
    this.analyticsS3Location = new S3Location(this, "AnalyticsS3Location", this.analyticsSourceBucket);

    // Output bucket
    this.outputBucket = createEncryptedBucket(this, "Bucket", "Metrics ETL Bucket Key");

    // Glue database
    const database = new glue.CfnDatabase(this, "Database", {
      catalogId: Aws.ACCOUNT_ID,
      databaseInput: { name: glueDatabaseName },
    });

    // Load schema and create tables
    const schemaPath = path.join(constants.PKG_ROOT, "prebid_server/prebid_metrics_schema.json");
    if (fs.existsSync(schemaPath)) {
      const schema: Record<string, Record<string, string>> = JSON.parse(fs.readFileSync(schemaPath, "utf-8"));
      for (const [tableName, columns] of Object.entries(schema)) {
        const table = new glue.CfnTable(this, `${tableName}Table`, {
          catalogId: Aws.ACCOUNT_ID,
          databaseName: glueDatabaseName,
          tableInput: {
            name: tableName.toLowerCase(),
            partitionKeys: [{ name: "year_month", type: "string" }],
            tableType: "EXTERNAL_TABLE",
            storageDescriptor: {
              columns: Object.entries(columns).map(([name, type]) => ({ name, type })),
              compressed: true,
              location: `s3://${this.outputBucket.bucketName}/type=${tableName.toLowerCase()}/`,
              storedAsSubDirectories: true,
              parameters: { classification: "parquet" },
              inputFormat: "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
              outputFormat: "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
              serdeInfo: { name: "ParquetHiveSerDe", serializationLibrary: "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe" },
            },
          },
        });
        table.node.addDependency(database);
      }
    }

    // Glue job
    const glueJobRole = new iam.Role(this, "JobRole", { assumedBy: GLUE_PRINCIPAL });
    glueJobRole.attachInlinePolicy(
      new iam.Policy(this, "JobPolicy", {
        statements: [
          new iam.PolicyStatement({
            actions: ["s3:GetObject", "s3:ListBucket"],
            resources: [
              artifactsConstruct.artifactsBucket.bucketArn, `${artifactsConstruct.artifactsBucket.bucketArn}/*`,
              this.metricsSourceBucket.bucketArn, `${this.metricsSourceBucket.bucketArn}/*`,
              this.outputBucket.bucketArn, `${this.outputBucket.bucketArn}/*`,
            ],
            conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } },
          }),
          new iam.PolicyStatement({ actions: ["s3:PutObject"], resources: [this.outputBucket.bucketArn, `${this.outputBucket.bucketArn}/*`], conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } } }),
          new iam.PolicyStatement({
            actions: ["glue:GetTable", "glue:GetDatabase", "glue:BatchCreatePartition", "glue:CreatePartition", "glue:GetPartition", "glue:GetPartitions", "glue:UpdatePartition", "glue:DeletePartition", "glue:BatchDeletePartition", "glue:BatchGetPartition"],
            resources: [`arn:aws:glue:${Aws.REGION}:${Aws.ACCOUNT_ID}:catalog`, `arn:aws:glue:${Aws.REGION}:${Aws.ACCOUNT_ID}:database/${glueDatabaseName}`, `arn:aws:glue:${Aws.REGION}:${Aws.ACCOUNT_ID}:table/${glueDatabaseName}/*`],
          }),
          new iam.PolicyStatement({ actions: ["athena:StartQueryExecution"], resources: [`arn:aws:athena:${Aws.REGION}:${Aws.ACCOUNT_ID}:workgroup/*`] }),
          new iam.PolicyStatement({ actions: ["s3:GetBucketLocation", "s3:PutObject"], resources: [artifactsConstruct.artifactsBucket.bucketArn, `${artifactsConstruct.artifactsBucket.bucketArn}/*`], conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } } }),
          new iam.PolicyStatement({ actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], resources: [`arn:${Aws.PARTITION}:logs:${Aws.REGION}:${Aws.ACCOUNT_ID}:log-group:/aws-glue/*`] }),
          new iam.PolicyStatement({ actions: ["cloudwatch:PutMetricData"], resources: ["*"] }),
        ],
      })
    );
    artifactsConstruct.artifactsBucket.encryptionKey?.grantEncryptDecrypt(glueJobRole);
    this.metricsSourceBucket.encryptionKey?.grantEncryptDecrypt(glueJobRole);
    this.outputBucket.encryptionKey?.grantEncryptDecrypt(glueJobRole);

    new glue.CfnJob(this, "Job", {
      command: { name: "glueetl", pythonVersion: "3", scriptLocation: `s3://${artifactsConstruct.artifactsBucket.bucketName}/glue/metrics_glue_script.py` },
      glueVersion: "5.0",
      role: glueJobRole.roleArn,
      defaultArguments: {
        "--SOURCE_BUCKET": this.metricsSourceBucket.bucketName,
        "--OUTPUT_BUCKET": this.outputBucket.bucketName,
        "--DATABASE_NAME": glueDatabaseName,
        "--AWS_REGION": Aws.REGION,
        "--ATHENA_QUERY_BUCKET": artifactsConstruct.artifactsBucket.bucketName,
        "--METRICS_NAMESPACE": this.node.tryGetContext("METRICS_NAMESPACE") ?? "",
        "--RESOURCE_PREFIX": Aws.STACK_NAME,
        "--SOLUTION_ID": this.node.tryGetContext("SOLUTION_ID") ?? "",
        "--SOLUTION_VERSION": this.node.tryGetContext("SOLUTION_VERSION") ?? "",
        "--enable-continuous-cloudwatch-log": "true",
        "--enable-metrics": "true",
        "--enable-observability-metrics": "true",
      },
      name: this.GLUE_JOB_NAME,
      executionProperty: { maxConcurrentRuns: constants.GLUE_MAX_CONCURRENT_RUNS },
      timeout: constants.GLUE_TIMEOUT_MINS,
    });

    // Glue trigger Lambda
    const triggerRole = new iam.Role(this, "TriggerFunctionRole", {
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
    this.lambdaFunction = new lambda.Function(this, "TriggerFunction", {
      role: triggerRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "start_glue_job.event_handler",
      code: pythonAssetCode(path.join(constants.PKG_ROOT, "prebid_server/glue_trigger_lambda")),
      description: "Lambda function for triggering metrics Glue Etl",
      memorySize: 256,
      timeout: Duration.minutes(5),
      architecture: lambda.Architecture.ARM_64,
      // SolutionsLayer is required transitively: start_glue_job.py imports
      // cloudwatch_metrics, whose metrics.py does
      //   `from aws_solutions.core.helpers import get_service_client`.
      // Without SolutionsLayer on the path this Lambda crashes at invoke with
      // ModuleNotFoundError: aws_solutions.
      layers: [PowertoolsLayer.getOrCreate(this), SolutionsLayer.getOrCreate(this), operationalMetricsLayer],
      environment: {
        GLUE_JOB_NAME: this.GLUE_JOB_NAME,
        RESOURCE_PREFIX: Aws.STACK_NAME,
        DATASYNC_REPORT_BUCKET: artifactsConstruct.artifactsBucket.bucketName,
        AWS_ACCOUNT_ID: Aws.ACCOUNT_ID,
        SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
        METRICS_NAMESPACE: this.node.tryGetContext("METRICS_NAMESPACE") ?? "",
      },
    });
    (this.lambdaFunction.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });
    this.lambdaFunction.role!.attachInlinePolicy(new iam.Policy(this, "LambdaPolicy", {
      statements: [
        new iam.PolicyStatement({ actions: ["cloudwatch:PutMetricData"], resources: ["*"], conditions: { StringEquals: { "cloudwatch:namespace": this.node.tryGetContext("METRICS_NAMESPACE") ?? "" } } }),
        new iam.PolicyStatement({ actions: ["glue:StartJobRun"], resources: [`arn:aws:glue:${Aws.REGION}:${Aws.ACCOUNT_ID}:job/${this.GLUE_JOB_NAME}`] }),
        new iam.PolicyStatement({ actions: ["s3:GetObject", "s3:ListBucket"], resources: [artifactsConstruct.artifactsBucket.bucketArn, `${artifactsConstruct.artifactsBucket.bucketArn}/*`], conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } } }),
      ],
    }));
    artifactsConstruct.artifactsBucket.encryptionKey?.grantEncryptDecrypt(this.lambdaFunction.role!);
    this.lambdaFunction.addPermission("InvokeLambda", {
      principal: new iam.ServicePrincipal("events.amazonaws.com"),
      action: "lambda:InvokeFunction",
    });
  }
}
