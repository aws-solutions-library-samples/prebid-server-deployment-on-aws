import { PowertoolsLayer, CrHelperLayer, SolutionsLayer, pythonAssetCode } from "../shared/lambda-helpers";
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// DataSync constructs: DataSyncMonitoring, EfsLocation, DataSyncTask, EfsCleanup, TaskReport
// These are ported from prebid_datasync_constructs.py

import { Aws, Duration, CustomResource } from "aws-cdk-lib";
import * as datasync from "aws-cdk-lib/aws-datasync";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as efs from "aws-cdk-lib/aws-efs";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";
import { S3Location } from "./glue-constructs";
import * as path from "path";

const DATASYNC_PRINCIPAL = new iam.ServicePrincipal("datasync.amazonaws.com");

const VPC_NW_INTERFACE_POLICY_STATEMENT = new iam.PolicyStatement({
  actions: ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"],
  resources: ["*"],
  conditions: { StringEquals: { [constants.RESOURCE_NAMESPACE]: [Aws.ACCOUNT_ID] } },
});

export class DataSyncMonitoring extends Construct {
  public readonly logGroup: logs.LogGroup;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    this.logGroup = new logs.LogGroup(this, "LogGroup");
    (this.logGroup.node.findChild("Resource") as logs.CfnLogGroup).addMetadata("guard", {
      SuppressedRules: ["CLOUDWATCH_LOG_GROUP_ENCRYPTED"],
    });

    new logs.ResourcePolicy(this, "ResourcePolicy", {
      policyStatements: [
        new iam.PolicyStatement({
          principals: [DATASYNC_PRINCIPAL],
          actions: ["logs:PutLogEvents", "logs:CreateLogStream"],
          resources: [`${this.logGroup.logGroupArn}:*`],
          conditions: { ArnLike: { "aws:SourceArn": [`arn:aws:datasync:${Aws.REGION}:${Aws.ACCOUNT_ID}:task/*`] } },
        }),
      ],
      resourcePolicyName: `${Aws.STACK_NAME}-DataSyncLogPolicy`,
    });
  }
}

export class EfsLocation extends Construct {
  public readonly efsLocation: datasync.CfnLocationEFS;

  constructor(scope: Construct, id: string, prebidVpc: ec2.IVpc, efsFilesystem: efs.FileSystem, efsPath: string, efsAp: efs.AccessPoint) {
    super(scope, id);

    const role = new iam.Role(this, "Role", { assumedBy: DATASYNC_PRINCIPAL });
    role.attachInlinePolicy(
      new iam.Policy(this, "Policy", {
        statements: [
          new iam.PolicyStatement({
            actions: ["elasticfilesystem:DescribeMountTargets", "elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite", "elasticfilesystem:ClientRootAccess"],
            resources: [efsFilesystem.fileSystemArn],
          }),
        ],
      })
    );

    const sg = new ec2.SecurityGroup(this, "SecurityGroup", { vpc: prebidVpc, allowAllOutbound: false });
    sg.connections.allowFrom(efsFilesystem, ec2.Port.tcp(constants.EFS_PORT));
    sg.connections.allowTo(efsFilesystem, ec2.Port.tcp(constants.EFS_PORT));

    const subnetId = prebidVpc.selectSubnets({ subnetGroupName: constants.PVT_SUBNET_NAME }).subnetIds[0];

    this.efsLocation = new datasync.CfnLocationEFS(this, "Location", {
      ec2Config: {
        securityGroupArns: [`arn:aws:ec2:${Aws.REGION}:${Aws.ACCOUNT_ID}:security-group/${sg.securityGroupId}`],
        subnetArn: `arn:aws:ec2:${Aws.REGION}:${Aws.ACCOUNT_ID}:subnet/${subnetId}`,
      },
      accessPointArn: efsAp.accessPointArn,
      inTransitEncryption: "TLS1_2",
      efsFilesystemArn: efsFilesystem.fileSystemArn,
      fileSystemAccessRoleArn: role.roleArn,
      subdirectory: efsPath,
    });
    this.efsLocation.node.addDependency(efsFilesystem);
  }
}

export interface DataSyncTaskProps {
  vpc: ec2.IVpc;
  efsFilesystem: efs.FileSystem;
  efsAp: efs.AccessPoint;
  efsPath: string;
  filterPattern: string;
  reportBucket: s3.Bucket;
  taskSchedule: string;
  logGroup: logs.LogGroup;
  glueEtlJobTrigger?: lambda.Function;
  glueEtlS3Location: S3Location;
  transferMode: string;
}

export class DataSyncTask extends Construct {
  public readonly task: datasync.CfnTask;

  constructor(scope: Construct, id: string, props: DataSyncTaskProps) {
    super(scope, id);

    const efsLoc = new EfsLocation(this, "EfsLocation", props.vpc, props.efsFilesystem, props.efsPath, props.efsAp);

    // Task report
    const reportRole = new iam.Role(this, "TaskReportRole", { assumedBy: DATASYNC_PRINCIPAL });
    const reportPolicy = new iam.Policy(this, "TaskReportPolicy", {
      statements: [
        new iam.PolicyStatement({
          actions: ["s3:PutObject", "s3:ListBucket"],
          resources: [props.reportBucket.bucketArn, `${props.reportBucket.bucketArn}/*`],
          // Mainline TaskReport._create_report_config() scopes this statement with
          // ACCOUNT_ID_CONDITION. Match it here (same condition V2 applies to the
          // container-stop lambda policy and VPC ENI policy) for least-privilege parity.
          conditions: { StringEquals: { [constants.RESOURCE_NAMESPACE]: [Aws.ACCOUNT_ID] } },
        }),
      ],
    });
    // Mainline: datasync_report_policy.node.add_dependency(self.bucket)
    reportPolicy.node.addDependency(props.reportBucket);
    reportRole.attachInlinePolicy(reportPolicy);
    props.reportBucket.encryptionKey?.grantEncryptDecrypt(reportRole);

    this.task = new datasync.CfnTask(this, "Task", {
      name: `${Aws.STACK_NAME}-${id}-task`,
      destinationLocationArn: props.glueEtlS3Location.s3Location.attrLocationArn,
      sourceLocationArn: efsLoc.efsLocation.attrLocationArn,
      schedule: { scheduleExpression: props.taskSchedule },
      options: { transferMode: props.transferMode, verifyMode: "ONLY_FILES_TRANSFERRED", logLevel: "BASIC" },
      excludes: [{ filterType: "SIMPLE_PATTERN", value: props.filterPattern }],
      taskReportConfig: {
        destination: {
          s3: { bucketAccessRoleArn: reportRole.roleArn, s3BucketArn: props.reportBucket.bucketArn, subdirectory: "datasync" },
        },
        objectVersionIds: "NONE",
        outputType: "STANDARD",
        reportLevel: "SUCCESSES_AND_ERRORS",
        overrides: {
          skipped: { reportLevel: "ERRORS_ONLY" },
          transferred: { reportLevel: "ERRORS_ONLY" },
        },
      },
      cloudWatchLogGroupArn: props.logGroup.logGroupArn,
    });
    // Mainline DataSyncTask adds explicit task deps on log_group, report_bucket,
    // s3_location and task_report. V2 inlines the task-report role/policy in this
    // construct (so the task auto-orders after them via the roleArn reference); the
    // remaining explicit deps are mirrored here.
    this.task.node.addDependency(props.logGroup);
    this.task.node.addDependency(props.reportBucket);
    this.task.node.addDependency(props.glueEtlS3Location);
    // Mainline: task.node.add_dependency(task_report) — the whole TaskReport
    // subtree (report role, its inline policy, and the grant-generated default
    // policy). V2 inlines those here, so depend on both the role (propagates to
    // its default policy from grantEncryptDecrypt) and the inline report policy.
    this.task.node.addDependency(reportRole);
    this.task.node.addDependency(reportPolicy);

    // EventBridge trigger
    const rule = new events.Rule(this, "EventBridgeRule", {
      eventPattern: {
        source: ["aws.datasync"],
        detailType: ["DataSync Task Execution State Change"],
        detail: { State: ["SUCCESS"] },
      },
    });
    (rule.node.defaultChild as events.CfnRule).addPropertyOverride(
      "EventPattern.resources",
      [{ wildcard: `${this.task.attrTaskArn}/execution/*` }]
    );
    // Mainline: rule.node.add_dependency(self.task). Needed so the rule (and its
    // auto-generated Lambda permission) order after the task; without it the
    // construct-scope deps populate the rule's DependsOn but omit the task,
    // diverging from Mainline.
    rule.node.addDependency(this.task);
    if (props.glueEtlJobTrigger) {
      rule.addTarget(new targets.LambdaFunction(props.glueEtlJobTrigger));
    }
  }
}

export interface EfsCleanupProps {
  vpc: ec2.IVpc;
  efsAp: efs.AccessPoint;
  efsFilesystem: efs.FileSystem;
  reportBucket: s3.Bucket;
  datasyncTasks: Record<string, datasync.CfnTask>;
  fargateClusterArn: string;
}

export class EfsCleanup extends Construct {
  public readonly efsFileDelLambdaFunction: lambda.Function;
  public readonly containerStopLambdaFunction: lambda.Function;

  constructor(scope: Construct, id: string, props: EfsCleanupProps) {
    super(scope, id);

    const sg = new ec2.SecurityGroup(this, "SecurityGroup", { vpc: props.vpc, allowAllOutbound: true });
    sg.connections.allowFrom(props.efsFilesystem, ec2.Port.tcp(constants.EFS_PORT));
    (sg.node.findChild("Resource") as ec2.CfnSecurityGroup).addMetadata("guard", {
      SuppressedRules: ["EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE", "SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE"],
    });

    const efsMount = lambda.FileSystem.fromEfsAccessPoint(props.efsAp, constants.EFS_MOUNT_PATH);
    const lambdaDir = path.join(constants.PKG_ROOT, "prebid_server/efs_cleanup_lambda");

    const efsDelRole = new iam.Role(this, "FunctionRole", {
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
    this.efsFileDelLambdaFunction = new lambda.Function(this, "Function", {
      role: efsDelRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "delete_efs_files.event_handler",
      code: pythonAssetCode(lambdaDir),
      securityGroups: [sg],
      vpc: props.vpc,
      filesystem: efsMount,
      description: "Lambda function for cleaning transferred files from EFS",
      memorySize: 256,
      timeout: Duration.minutes(15),
      architecture: lambda.Architecture.ARM_64,
      // SolutionsLayer is required transitively: delete_efs_files.py imports
      // cloudwatch_metrics, whose metrics.py imports aws_solutions.core.helpers.
      // (operationalMetricsLayer + datasyncS3Layer are attached at the entry
      // deployment via addLayers.)
      layers: [PowertoolsLayer.getOrCreate(this), SolutionsLayer.getOrCreate(this)],
      environment: {
        EFS_MOUNT_PATH: constants.EFS_MOUNT_PATH,
        METRICS_TASK_ARN: props.datasyncTasks["metrics"].attrTaskArn,
        ANALYTICS_TASK_ARN: props.datasyncTasks["analytics"].attrTaskArn,
        RESOURCE_PREFIX: Aws.STACK_NAME,
        DATASYNC_REPORT_BUCKET: props.reportBucket.bucketName,
        AWS_ACCOUNT_ID: Aws.ACCOUNT_ID,
        EFS_METRICS: constants.EFS_METRICS,
        EFS_ANALYTICS: constants.EFS_ANALYTICS,
        EFS_LOGS: constants.EFS_LOGS,
        SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
        METRICS_NAMESPACE: this.node.tryGetContext("METRICS_NAMESPACE") ?? "",
      },
    });
    (this.efsFileDelLambdaFunction.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", { SuppressedRules: ["LAMBDA_CONCURRENCY_CHECK"] });
    props.efsFilesystem.grantReadWrite(this.efsFileDelLambdaFunction.role!);
    props.reportBucket.encryptionKey?.grantEncryptDecrypt(this.efsFileDelLambdaFunction.role!);

    this.efsFileDelLambdaFunction.role!.attachInlinePolicy(new iam.Policy(this, "LambdaPolicy", {
      statements: [
        VPC_NW_INTERFACE_POLICY_STATEMENT,
        new iam.PolicyStatement({ actions: ["cloudwatch:PutMetricData"], resources: ["*"], conditions: { StringEquals: { "cloudwatch:namespace": this.node.tryGetContext("METRICS_NAMESPACE") ?? "" } } }),
        new iam.PolicyStatement({ actions: ["s3:GetObject", "s3:ListBucket"], resources: [props.reportBucket.bucketArn, `${props.reportBucket.bucketArn}/*`], conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } } }),
      ],
    }));

    // EventBridge trigger for EFS cleanup on DataSync success
    this.efsFileDelLambdaFunction.addPermission("InvokeLambda", {
      principal: new iam.ServicePrincipal("events.amazonaws.com"),
      action: "lambda:InvokeFunction",
    });
    const cleanupRule = new events.Rule(this, "EventBridgeRule", {
      eventPattern: {
        source: ["aws.datasync"],
        detailType: ["DataSync Task Execution State Change"],
        detail: { State: ["SUCCESS"] },
      },
    });
    (cleanupRule.node.defaultChild as events.CfnRule).addPropertyOverride(
      "EventPattern.resources",
      Object.values(props.datasyncTasks).map(task => ({ wildcard: `${task.attrTaskArn}/execution/*` }))
    );
    cleanupRule.addTarget(new targets.LambdaFunction(this.efsFileDelLambdaFunction));

    // Container stop logs Lambda
    const containerStopRole = new iam.Role(this, "ContainerStopFunctionRole", {
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
    this.containerStopLambdaFunction = new lambda.Function(this, "ContainerStopFunction", {
      role: containerStopRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "container_stop_logs.event_handler",
      code: pythonAssetCode(lambdaDir),
      securityGroups: [sg],
      vpc: props.vpc,
      filesystem: efsMount,
      description: "Lambda function for archiving logs on container stopping",
      timeout: Duration.seconds(60),
      memorySize: 256,
      architecture: lambda.Architecture.ARM_64,
      // SolutionsLayer is required transitively: container_stop_logs.py imports
      // cloudwatch_metrics, whose metrics.py imports aws_solutions.core.helpers.
      layers: [PowertoolsLayer.getOrCreate(this), SolutionsLayer.getOrCreate(this)],
      environment: {
        EFS_MOUNT_PATH: constants.EFS_MOUNT_PATH,
        EFS_METRICS: constants.EFS_METRICS,
        EFS_ANALYTICS: constants.EFS_ANALYTICS,
        EFS_LOGS: constants.EFS_LOGS,
        RESOURCE_PREFIX: Aws.STACK_NAME,
        SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
        METRICS_NAMESPACE: this.node.tryGetContext("METRICS_NAMESPACE") ?? "",
      },
    });
    (this.containerStopLambdaFunction.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", { SuppressedRules: ["LAMBDA_CONCURRENCY_CHECK"] });
    props.efsFilesystem.grantReadWrite(this.containerStopLambdaFunction.role!);

    this.containerStopLambdaFunction.role!.attachInlinePolicy(new iam.Policy(this, "ContainerLambdaPolicy", {
      statements: [
        VPC_NW_INTERFACE_POLICY_STATEMENT,
        new iam.PolicyStatement({ actions: ["cloudwatch:PutMetricData"], resources: ["*"], conditions: { StringEquals: { "cloudwatch:namespace": this.node.tryGetContext("METRICS_NAMESPACE") ?? "" } } }),
      ],
    }));

    // Container stop EventBridge trigger.
    // Task 9.6: mirror Mainline's _create_container_stop_logs_lambda_trigger, which
    // adds an explicit InvokeLambda permission for the events principal in addition
    // to the permission the rule target auto-generates (same pattern V2 already uses
    // for efsFileDelLambdaFunction above). Without it V2 was missing one
    // AWS::Lambda::Permission per entry deployment vs Mainline (parity presence gap).
    this.containerStopLambdaFunction.addPermission("InvokeLambda", {
      principal: new iam.ServicePrincipal("events.amazonaws.com"),
      action: "lambda:InvokeFunction",
    });
    const containerRule = new events.Rule(this, "ContainerLambdaEventBridgeRule", {
      eventPattern: {
        source: ["aws.ecs"],
        detailType: ["ECS Task State Change"],
        detail: { lastStatus: ["STOPPING"], clusterArn: [props.fargateClusterArn] },
      },
    });
    containerRule.addTarget(new targets.LambdaFunction(this.containerStopLambdaFunction));

    // VPC ENI cleanup custom resource
    const eniRole = new iam.Role(this, "CrRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      inlinePolicies: {
        LambdaCrLoggingPolicy: new iam.PolicyDocument({
          statements: [new iam.PolicyStatement({
            actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            resources: [`arn:${Aws.PARTITION}:logs:${Aws.REGION}:${Aws.ACCOUNT_ID}:log-group:/aws/lambda/*`],
          })],
        }),
        LambdaCrEniPolicy: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({ actions: ["ec2:DeleteNetworkInterface"], resources: ["*"], conditions: { StringEquals: { "ec2:Vpc": (props.vpc as ec2.Vpc).vpcArn } } }),
            new iam.PolicyStatement({ actions: ["ec2:DescribeNetworkInterfaces", "ec2:DetachNetworkInterface"], resources: ["*"], conditions: { StringEquals: { [constants.RESOURCE_NAMESPACE]: [Aws.ACCOUNT_ID] } } }),
          ],
        }),
      },
    });

    const eniFn = new lambda.Function(this, "VpcEniFunction", {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "delete_lambda_eni.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "vpc_eni_lambda")),
      role: eniRole,
      description: "Lambda function for deleting VPC ENIs for the Lambda service",
      memorySize: 256,
      architecture: lambda.Architecture.ARM_64,
      environment: { SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "", SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "" },
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this)],
    });
    (eniFn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });

    const eniCr = new CustomResource(this, "VpcEniCr", {
      serviceToken: eniFn.functionArn,
      properties: { SECURITY_GROUP_ID: sg.securityGroupId },
    });
    this.efsFileDelLambdaFunction.node.addDependency(eniCr);
    this.containerStopLambdaFunction.node.addDependency(eniCr);
  }
}
