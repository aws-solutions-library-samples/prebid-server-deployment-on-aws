# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import Aws, Duration
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_logs as logs
from aws_cdk import aws_iam as iam
from constructs import Construct
import prebid_server.stack_constants as stack_constants

class ECSTaskConstruct(Construct):
    def __init__(
            self,
            scope,
            id,
            image_ecs_obj,
            prebid_fs,
            prebid_fs_access_point,
            docker_configs_manager_bucket,
            stored_requests_bucket
    ) -> None:
        """
        This construct creates EFS resources.
        """
        super().__init__(scope, id)

        # Create Task Definition
        self.prebid_task_definition = ecs.FargateTaskDefinition(
            self,
            "PrebidTaskDef",
            cpu=stack_constants.VCPU,
            memory_limit_mib=stack_constants.MEMORY_LIMIT_MIB,
        )

        # Add EFS volume to task definition
        self.prebid_task_definition.add_volume(
            name=stack_constants.EFS_VOLUME_NAME,
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=prebid_fs.file_system_id,
                transit_encryption="ENABLED",
                authorization_config=ecs.AuthorizationConfig(
                    access_point_id=prebid_fs_access_point.access_point_id,
                    iam="ENABLED",
                ),
            ),
        )

        private_ecr_repo_policy_actions = [
            "ecr:BatchCheckLayerAvailability",
            "ecr:GetDownloadUrlForLayer",
            "ecr:BatchGetImage",
            "ecr:DescribeImages",
            "ecr:GetAuthorizationToken"
        ]

        # Public ECR IAM policy to task definition
        self.prebid_task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
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
                    *private_ecr_repo_policy_actions
                ],
                resources=["*"],  # NOSONAR
            )
        )

        self.prebid_task_definition.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=private_ecr_repo_policy_actions,
                resources=["*"],  # NOSONAR
            )
        )

        # Configure log capture for AWS Logs driver
        log_group = logs.LogGroup(self, "PrebidContainerLogGroup")
        # Suppress cfn_guard rule for CloudWatch log encryption since they are
        # encrypted by default.
        log_group_l1_construct = log_group.node.find_child(id="Resource")
        log_group_l1_construct.add_metadata(
            "guard", {
                'SuppressedRules': ['CLOUDWATCH_LOG_GROUP_ENCRYPTED']
            }
        )
        log_driver = ecs.LogDriver.aws_logs(
            stream_prefix="Prebid", mode=ecs.AwsLogDriverMode.NON_BLOCKING, log_group=log_group
        )

        # Add Container to Task Definition
        self.prebid_container = self.prebid_task_definition.add_container(
            "Prebid-Container",
            image=image_ecs_obj,
            port_mappings=[ecs.PortMapping(container_port=stack_constants.CONTAINER_PORT)],
            logging=log_driver,
            environment={
                "ECS_ENABLE_SPOT_INSTANCE_DRAINING": "true",
                "DOCKER_CONFIGS_S3_BUCKET_NAME": docker_configs_manager_bucket.bucket_name,
                "SETTINGS_S3_BUCKET": stored_requests_bucket.bucket_name,
                "SETTINGS_S3_ENDPOINT": f"https://s3.{Aws.REGION}.amazonaws.com",
                "SETTINGS_S3_REGION": f"{Aws.REGION}"
            },
            health_check={
                "command": [
                    "CMD-SHELL", f"curl -k -f {stack_constants.HEALTH_ENDPOINT} || exit 1",
                ],
                "interval": Duration.seconds(stack_constants.HEALTH_CHECK_INTERVAL_SECS),
                "timeout": Duration.seconds(stack_constants.HEALTH_CHECK_TIMEOUT_SECS)
            }
        )

        self.prebid_container.node.add_dependency(docker_configs_manager_bucket)

        self.prebid_task_definition.add_to_execution_role_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:{Aws.PARTITION}:logs:{Aws.REGION}:{Aws.ACCOUNT_ID}:log-group:{Aws.STACK_NAME}-PrebidContainerLogGroup*"
                ],
            )
        )

        s3_policy_actions = ["s3:GetObject", "s3:ListBucket"]

        self.prebid_task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=s3_policy_actions,
                resources=[
                    f"{docker_configs_manager_bucket.bucket_arn}/*",
                    docker_configs_manager_bucket.bucket_arn,
                    f"{stored_requests_bucket.bucket_arn}/*",
                    stored_requests_bucket.bucket_arn
                ],
            )
        )

        # Add mount points to container
        self.prebid_container.add_mount_points(
            ecs.MountPoint(
                container_path=stack_constants.EFS_MOUNT_PATH,
                source_volume=stack_constants.EFS_VOLUME_NAME,
                read_only=False,
            )
        )

        self.prebid_task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
                    "elasticfilesystem:ClientRootAccess",
                    "elasticfilesystem:ClientWrite",
                    "elasticfilesystem:ClientMount",
                    "elasticfilesystem:DescribeMountTargets",
                ],
                resources=[
                    f"arn:aws:elasticfilesystem:{Aws.REGION}:{Aws.ACCOUNT_ID}:file-system/{prebid_fs.file_system_id}"
                ],
            )
        )

        self.prebid_task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["ec2:DescribeAvailabilityZones"], resources=["*"]
            )
        )
