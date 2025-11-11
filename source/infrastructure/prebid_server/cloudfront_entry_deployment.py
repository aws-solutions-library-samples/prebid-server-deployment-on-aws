# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import (
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    Duration
)
from aws_cdk import Aspects, CfnOutput
from .condition_aspect import ConditionAspect
from .alb_access_logs_construct import AlbAccessLogsConstruct
from constructs import Construct
import prebid_server.stack_constants as stack_constants
from .prebid_datasync_constructs import EfsCleanup, DataSyncTask
from .efs_construct import EfsConstruct
from .ecs_task_construct import ECSTaskConstruct
from .ecs_service_construct import ECSServiceConstruct
from .cloudfront_waf_construct import CloudFrontWafConstruct
from .cloudwatch_alarms_construct import CloudwatchAlarms
from .cloudwatch_metrics_construct import CloudwatchMetricsConstruct
from .cloudwatch_dashboard_construct import CloudFrontDeploymentDashboard


class CloudFrontEntryDeployment(Construct):
    def __init__(
            self,  # NOSONAR (python:S107) - allow large number of method parameters
            scope,
            id,
            stack_params,
            deploy_cloudfront_waf_condition,
            artifacts_construct,
            datasync_monitor,
            vpc_construct,
            container_image_construct,
            datasync_s3_layer,
            prebid_cluster,
            glue_etl,
            lambda_target_external_cf,
            lambda_target_internal,
            x_header_secret_value,
            stored_requests_bucket,
            cache_lambda_name,
            elasticache_cluster_id,
            operational_metrics_layer,
    ) -> None:
        """
        This construct creates resources needed for the user to use CloudFront as their CDN.
        """
        super().__init__(scope, id)

        # Apply condition to resources in this construct
        Aspects.of(self).add(ConditionAspect(self, "Condition", deploy_cloudfront_waf_condition))

        prebid_vpc = vpc_construct.prebid_vpc
        prebid_task_subnets = vpc_construct.prebid_task_subnets
        image_ecs_obj = container_image_construct.image_ecs_obj
        docker_configs_manager_bucket = container_image_construct.docker_configs_manager_bucket

        efs_construct = EfsConstruct(self, "Efs", prebid_vpc)

        ecs_task_construct = ECSTaskConstruct(self, "ECSTask", image_ecs_obj, efs_construct.prebid_fs,
                                              efs_construct.prebid_fs_access_point,
                                              docker_configs_manager_bucket,
                                              stored_requests_bucket)

        # ALB security group
        alb_sec_group = ec2.SecurityGroup(self, "Prebid-ALB-security-group", vpc=prebid_vpc)  # NOSONAR
        # Suppress cfn_guard warning about open egress in the ALB security
        # group because Prebid Server containers require open egress in order
        # to connect to demand partners.
        #
        # The cfn_guard warning about open ingress and non-32 rule is also
        # suppressed because Prebid Server containers require open ingress in
        # order to connect to clients through the Internet facing ALB.
        security_group_l1_construct = alb_sec_group.node.find_child(id='Resource')
        security_group_l1_construct.add_metadata("guard", {
            'SuppressedRules': [
                'EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE',
                'SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE',
                'EC2_SECURITY_GROUP_INGRESS_OPEN_TO_WORLD_RULE',
                'SECURITY_GROUP_INGRESS_CIDR_NON_32_RULE'
            ]})

        # Create Application Load Balancer
        prebid_alb = elbv2.ApplicationLoadBalancer(
            self,
            "Prebid-ALB",
            vpc=prebid_vpc,
            internet_facing=True,
            security_group=alb_sec_group,
        )

        # Suppress cfn_guard warning about access logs in the ALB because
        # access logs are added to the ALB in alb_access_logs_construct.py
        prebid_alb_l1_construct = prebid_alb.node.find_child(id="Resource")
        prebid_alb_l1_construct.add_metadata("guard", {'SuppressedRules': ['ELBV2_ACCESS_LOGGING_RULE']})

        # Set up ALB Listener Rule
        http_listener = prebid_alb.add_listener("HTTPListener", port=80, protocol=elbv2.ApplicationProtocol.HTTP,
                                                default_action=elbv2.ListenerAction.fixed_response(
                                                    status_code=401, content_type="text/plain",
                                                    message_body="Unauthorized"))

        # Suppress cfn_guard warning about an absent SslPolicy. This is an HTTP listener.
        # This listener is only used for HTTP traffic on the VPC between Cloudfront and
        # Prebid Server runtimes.
        http_listener.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['ELBV2_LISTENER_SSL_POLICY_RULE', 'ELBV2_LISTENER_PROTOCOL_RULE']})

        ecs_service_construct = ECSServiceConstruct(self, "ECSService",
                                                    stack_params,
                                                    prebid_vpc,
                                                    prebid_cluster,
                                                    ecs_task_construct.prebid_task_definition,
                                                    prebid_task_subnets,
                                                    ecs_task_construct.prebid_container,
                                                    efs_construct.prebid_fs)

        ecs_task_construct.prebid_container.add_environment(
            name="CACHE_HOST",
            value=ecs_service_construct.internal_prebid_alb.load_balancer_dns_name
        )

        # Create CloudFront and WAF resources, and prefix list id.
        cloudfront_waf_construct = CloudFrontWafConstruct(self, "CloudFrontWaf", prebid_alb, x_header_secret_value)

        # Create a rule for the HTTP listener in the ALB that forwards incoming requests to the prebid cluster.
        # After the rule is configured, the Fargate service running on the prebid cluster is fronted by the ALB.
        elbv2.ApplicationListenerRule(
            self,
            "PrebidListenerRule1",
            listener=http_listener,
            priority=5,
            conditions=[
                elbv2.ListenerCondition.http_header(
                    stack_constants.X_SECRET_HEADER_NAME, [x_header_secret_value]
                )
            ],
            action=elbv2.ListenerAction.forward(
                [
                    ecs_service_construct.alb_target_group
                ]
            ),
        )

        # Add the new listener rule for /cache endpoint
        elbv2.ApplicationListenerRule(
            self,
            "CacheListenerRuleCloudFront",
            listener=http_listener,
            priority=2,
            conditions=[
                elbv2.ListenerCondition.path_patterns(["/cache", "/cache/*"]),
                elbv2.ListenerCondition.http_header(
                    stack_constants.X_SECRET_HEADER_NAME, [x_header_secret_value]
                ),
                elbv2.ListenerCondition.http_request_methods(["GET"])
            ],
            action=elbv2.ListenerAction.forward([lambda_target_external_cf]),
        )

        # Add the new listener rule for /cache endpoint for internal ALB
        elbv2.ApplicationListenerRule(
            self,
            "CacheListenerRuleCloudFrontInternal",
            listener=ecs_service_construct.internal_http_listener,
            priority=1,
            conditions=[
                elbv2.ListenerCondition.path_patterns(["/cache", "/cache/*"]),
                elbv2.ListenerCondition.http_request_methods(["GET", "POST"])
            ],
            action=elbv2.ListenerAction.forward([lambda_target_internal]),
        )

        CfnOutput(
            self,
            "Prebid-CloudFrontDistributionEndpoint",
            key="PrebidCloudFrontDistributionEndpoint",
            value=cloudfront_waf_construct.prebid_cloudfront_distribution.domain_name,
            description="Prebid CloudFront Distribution Endpoint",
        )

        CfnOutput(self, "Prebid-WAF-WebACL",
                  key="PrebidWAFWebACL",
                  value=cloudfront_waf_construct.waf_webacl_name,
                  description="Prebid WAF WebACL",
                  )

        # Create ingress rule for the ALB that allows incoming traffic only from CloudFront.
        alb_sec_group.add_ingress_rule(
            peer=ec2.Peer.prefix_list(cloudfront_waf_construct.prefix_list_id),
            connection=ec2.Port.tcp(80),
            description="Allow ingress only from CloudFront",
        )

        # Setup auto-scaling rule for the Fargate service.
        # Note that this can only be done after the ALB listener rule has been created, this the scaling rule relies on the ALB to route incoming requests to the Fargate service.
        # The order in which resources are created matters here, so be sure to create the ALB listener rule before setting up this auto-scaling rule
        
        # Add CPU and memory scaling first
        ecs_service_construct.add_cpu_scaling()
        ecs_service_construct.add_memory_scaling()
        
        # Create the ALB request count scaling policy after the listener is created
        ecs_service_construct.add_alb_request_count_scaling(
            target_group=ecs_service_construct.alb_target_group,
            requests_per_target=stack_params.request_count_threshold.value_as_number
        )

        # Create DataSync tasks for moving logs and metrics from EFS to S3
        datasync_metrics = DataSyncTask(
            self,
            "DataSyncMetrics",
            vpc=prebid_vpc,
            efs_filesystem=efs_construct.prebid_fs,
            efs_ap=efs_construct.prebid_fs_access_point,
            efs_path=stack_constants.EFS_METRICS,
            filter_pattern="*/prebid-metrics.log",
            task_schedule=stack_constants.DATASYNC_METRICS_SCHEDULE,
            report_bucket=artifacts_construct.artifacts_bucket,
            log_group=datasync_monitor.log_group,
            glue_etl_job_trigger=glue_etl.lambda_function,
            glue_etl_s3_location=glue_etl.metrics_s3_location,
            transfer_mode="CHANGED"
        )

        datasync_metrics.node.add_dependency(artifacts_construct.artifacts_bucket)
        datasync_metrics.node.add_dependency(datasync_monitor.log_group)

        # Create DataSync tasks for moving logs and analytics from EFS to S3
        datasync_analytics = DataSyncTask(
            self,
            "DataSyncAnalytics",
            vpc=prebid_vpc,
            efs_filesystem=efs_construct.prebid_fs,
            efs_ap=efs_construct.prebid_fs_access_point,
            efs_path=stack_constants.EFS_ANALYTICS,
            filter_pattern="*/prebid-analytics.log",
            task_schedule=stack_constants.DATASYNC_ANALYTICS_SCHEDULE,
            report_bucket=artifacts_construct.artifacts_bucket,
            log_group=datasync_monitor.log_group,
            glue_etl_job_trigger=None,
            glue_etl_s3_location=glue_etl.analytics_s3_location,
            transfer_mode="ALL"
        )

        datasync_analytics.node.add_dependency(artifacts_construct.artifacts_bucket)
        datasync_analytics.node.add_dependency(datasync_monitor.log_group)

        # Suppress cfn_guard warning about missing egress rule. Justification:
        # The Datasync construct creates a security group without an efgress rule.
        # Security groups without an egress rule allow all outbound traffic by default.
        # Datasync lies within our trust domain. We trust outbound traffic from that service.

        self.add_security_group_suppression(datasync_metrics)
        self.add_security_group_suppression(datasync_analytics)

        # Create resources for removing transferred logs and metrics from EFS
        efs_cleanup = EfsCleanup(
            self,
            "EfsCleanup",
            vpc=prebid_vpc,
            efs_ap=efs_construct.prebid_fs_access_point,
            efs_filesystem=efs_construct.prebid_fs,
            report_bucket=artifacts_construct.artifacts_bucket,
            datasync_tasks={
                stack_constants.EFS_METRICS: datasync_metrics.task,
                stack_constants.EFS_ANALYTICS: datasync_analytics.task,
            },
            fargate_cluster_arn=prebid_cluster.cluster_arn,
            operational_metrics_layer=operational_metrics_layer,
        )
        efs_cleanup.efs_file_del_lambda_function.add_layers(datasync_s3_layer)

        CfnOutput(self, "Prebid-EFSId", value=efs_construct.prebid_fs.file_system_id, description="Prebid EFS Id")

        # CloudWatch Alarms
        CloudwatchAlarms(
            self,
            "CloudwatchAlarms",
            application_load_balancer=prebid_alb,
            efs_file_system=efs_construct.prebid_fs,
            vpc=prebid_vpc,
            cloudfront_distribution=cloudfront_waf_construct.prebid_cloudfront_distribution,
            waf_webacl_name=cloudfront_waf_construct.waf_webacl_name,
            glue_job_name=glue_etl.GLUE_JOB_NAME,
        )

        # CloudWatch Metrics
        CloudwatchMetricsConstruct(
            self,
            "cloudwatch-metrics",
            cloud_front_id=cloudfront_waf_construct.prebid_cloudfront_distribution.distribution_id,
            public_subnets=[
                public_subnet.subnet_id for public_subnet in prebid_vpc.public_subnets
            ],
            load_balancer_full_name=prebid_alb.load_balancer_full_name,
            elasticache_cluster_id=elasticache_cluster_id,
        )

        # Dashboard
        CloudFrontDeploymentDashboard(
            self,
            "PrebidDashboard",
            application_load_balancer=prebid_alb,
            efs_file_system=efs_construct.prebid_fs,
            vpc=prebid_vpc,
            glue_job_name=glue_etl.GLUE_JOB_NAME,
            cloudfront_distribution=cloudfront_waf_construct.prebid_cloudfront_distribution,
            waf_webacl_name=cloudfront_waf_construct.waf_webacl_name,
            ecs_cluster_name=prebid_cluster.cluster_name,
            ecs_service_name=ecs_service_construct.service_name,
            alb_target_group=ecs_service_construct.alb_target_group,
            cache_target_group=lambda_target_internal,
            cache_alb=ecs_service_construct.internal_prebid_alb,
            data_sync_metrics_bucket_name=glue_etl.metrics_source_bucket.bucket_name,
            metrics_etl_bucket_name=glue_etl.output_bucket.bucket_name,
            cache_lambda_name=cache_lambda_name,
            efs_cleanup_lambda_name=efs_cleanup.efs_file_del_lambda_function.function_name,
            container_stop_lambda_name=efs_cleanup.container_stop_lambda_function.function_name,
            glue_trigger_lambda_name=glue_etl.lambda_function.function_name,
            elasticache_cluster_id=elasticache_cluster_id,
        )

        # Construct to create custom resource to enable access logging for ALB
        AlbAccessLogsConstruct(
            self, "ALBAccessLogsConstruct", alb_arn=prebid_alb.load_balancer_arn
        )

        # Store references to resources needed by other constructs
        self.prebid_alb = prebid_alb
        self.prebid_cloudfront_distribution = cloudfront_waf_construct.prebid_cloudfront_distribution
        self.waf_webacl_name = cloudfront_waf_construct.waf_webacl_name

    def add_security_group_suppression(self, construct: Construct) -> None:
        """
        Add cfn_guard suppression rule to all security groups in a construct
        
        Args:
            construct: The CDK construct containing security groups
        """
        for child in construct.node.find_all():
            if isinstance(child, ec2.SecurityGroup):
                security_group_l1_construct = child.node.find_child(id="Resource")
                security_group_l1_construct.add_metadata(
                    "guard",
                    {'SuppressedRules': ["SECURITY_GROUP_MISSING_EGRESS_RULE"]}
                )
