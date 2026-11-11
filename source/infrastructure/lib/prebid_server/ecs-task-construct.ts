// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, Duration, Fn } from "aws-cdk-lib";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import { StackParams } from "./stack-cfn-parameters";
import * as constants from "../shared/stack-constants";

export interface EcsTaskConstructProps {
  imageEcsObj: ecs.ContainerImage;
  prebidFs: efs.FileSystem;
  prebidFsAccessPoint: efs.AccessPoint;
  dockerConfigsBucket: s3.IBucket;
  storedRequestsBucket: s3.IBucket;
  /**
   * When provided, the ECS container environment variables are derived from
   * CloudFormation parameters and CfnConditions (deploy-time resolution). When
   * omitted, the legacy synth-time `simulatorEndpoint`/`enableAnalytics`
   * derivation is used.
   */
  stackParams?: StackParams;
  simulatorEndpoint?: string;
  enableAnalytics?: boolean;
}

export class EcsTaskConstruct extends Construct {
  public readonly taskDefinition: ecs.FargateTaskDefinition;
  public readonly container: ecs.ContainerDefinition;

  constructor(scope: Construct, id: string, props: EcsTaskConstructProps) {
    super(scope, id);

    this.taskDefinition = new ecs.FargateTaskDefinition(this, "PrebidTaskDef", {
      cpu: constants.VCPU,
      memoryLimitMiB: constants.MEMORY_LIMIT_MIB,
    });

    // EFS volume
    this.taskDefinition.addVolume({
      name: constants.EFS_VOLUME_NAME,
      efsVolumeConfiguration: {
        fileSystemId: props.prebidFs.fileSystemId,
        transitEncryption: "ENABLED",
        authorizationConfig: {
          accessPointId: props.prebidFsAccessPoint.accessPointId,
          iam: "ENABLED",
        },
      },
    });

    // ECR policies
    this.taskDefinition.addToTaskRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "ecr-public:GetAuthorizationToken",
          "sts:GetServiceBearerToken",
          "ecr-public:BatchCheckLayerAvailability",
          "ecr-public:GetRepositoryPolicy",
          "ecr-public:DescribeRepositories",
          "ecr-public:DescribeRegistries",
          "ecr-public:DescribeImages",
          "ecr-public:DescribeImageTags",
          "ecr-public:GetRepositoryCatalogData",
          "ecr-public:GetRegistryCatalogData",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:DescribeImages",
          "ecr:GetAuthorizationToken",
        ],
        resources: ["*"],
      })
    );

    this.taskDefinition.addToExecutionRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:DescribeImages",
          "ecr:GetAuthorizationToken",
        ],
        resources: ["*"],
      })
    );

    // Log group
    const logGroup = new logs.LogGroup(this, "PrebidContainerLogGroup");
    (logGroup.node.findChild("Resource") as logs.CfnLogGroup).addMetadata("guard", {
      SuppressedRules: ["CLOUDWATCH_LOG_GROUP_ENCRYPTED"],
    });

    // Determine environment variable values.
    //   New path (stackParams provided): CfnConditions/CFN params → deploy-time resolution.
    //   Legacy path: Python-side synth-time derivation.
    let amtEnabled: string;
    let amtEndpoint: string;
    let analyticsEnabled: string;
    if (props.stackParams) {
      const sp = props.stackParams;
      // AMT_ADAPTER_ENABLED: "true" when HasSimulatorEndpoint, else "false".
      amtEnabled = Fn.conditionIf(sp.hasSimulatorEndpoint.logicalId, "true", "false").toString();
      // AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT:
      //   At deploy time the endpoint is empty unless VPC-peering SimulatorEndpoint is provided.
      //   RTB Fabric path: simulator_fabric_link.py populates it later via the ECS API
      //   (registers a new task-def revision). Prebid Server validates adapter endpoint
      //   URLs even when the adapter is disabled, so use a placeholder URL (not empty)
      //   to prevent a startup failure.
      amtEndpoint = Fn.conditionIf(
        sp.hasSimulatorEndpoint.logicalId,
        sp.simulatorEndpointParam.valueAsString,
        "https://localhost/not-configured"
      ).toString();
      // LOG_ANALYTICS_ENABLED: direct reference to the CF parameter.
      analyticsEnabled = sp.enableLogAnalyticsParam.valueAsString;
    } else {
      amtEnabled = props.simulatorEndpoint ? "true" : "false";
      amtEndpoint = props.simulatorEndpoint ?? "bidder-simulator-endpoint";
      analyticsEnabled = props.enableAnalytics ? "true" : "false";
    }

    this.container = this.taskDefinition.addContainer("Prebid-Container", {
      image: props.imageEcsObj,
      portMappings: [{ containerPort: constants.CONTAINER_PORT }],
      logging: ecs.LogDriver.awsLogs({
        streamPrefix: "Prebid",
        mode: ecs.AwsLogDriverMode.NON_BLOCKING,
        logGroup,
      }),
      environment: {
        AMT_ADAPTER_ENABLED: amtEnabled,
        LOG_ANALYTICS_ENABLED: analyticsEnabled,
        AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT: amtEndpoint,
        ECS_ENABLE_SPOT_INSTANCE_DRAINING: "true",
        DOCKER_CONFIGS_S3_BUCKET_NAME: props.dockerConfigsBucket.bucketName,
        SETTINGS_S3_BUCKET: props.storedRequestsBucket.bucketName,
        SETTINGS_S3_ENDPOINT: `https://s3.${Aws.REGION}.amazonaws.com`,
        SETTINGS_S3_REGION: Aws.REGION,
      },
      healthCheck: {
        command: ["CMD-SHELL", `curl -k -f ${constants.HEALTH_ENDPOINT} || exit 1`],
        interval: Duration.seconds(constants.HEALTH_CHECK_INTERVAL_SECS),
        timeout: Duration.seconds(constants.HEALTH_CHECK_TIMEOUT_SECS),
      },
    });

    // Logging permissions
    this.taskDefinition.addToExecutionRolePolicy(
      new iam.PolicyStatement({
        actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        resources: [
          `arn:${Aws.PARTITION}:logs:${Aws.REGION}:${Aws.ACCOUNT_ID}:log-group:${Aws.STACK_NAME}-PrebidContainerLogGroup*`,
        ],
      })
    );

    // S3 access for config and stored requests
    this.taskDefinition.addToTaskRolePolicy(
      new iam.PolicyStatement({
        actions: ["s3:GetObject", "s3:ListBucket"],
        resources: [
          `${props.dockerConfigsBucket.bucketArn}/*`,
          props.dockerConfigsBucket.bucketArn,
          `${props.storedRequestsBucket.bucketArn}/*`,
          props.storedRequestsBucket.bucketArn,
        ],
      })
    );

    // EFS mount
    this.container.addMountPoints({
      containerPath: constants.EFS_MOUNT_PATH,
      sourceVolume: constants.EFS_VOLUME_NAME,
      readOnly: false,
    });

    // EFS permissions
    this.taskDefinition.addToTaskRolePolicy(
      new iam.PolicyStatement({
        actions: [
          "elasticfilesystem:ClientRootAccess",
          "elasticfilesystem:ClientWrite",
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:DescribeMountTargets",
        ],
        resources: [
          `arn:aws:elasticfilesystem:${Aws.REGION}:${Aws.ACCOUNT_ID}:file-system/${props.prebidFs.fileSystemId}`,
        ],
      })
    );

    this.taskDefinition.addToTaskRolePolicy(
      new iam.PolicyStatement({
        actions: ["ec2:DescribeAvailabilityZones"],
        resources: ["*"],
      })
    );
  }
}
