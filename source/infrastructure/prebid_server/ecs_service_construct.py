# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import Duration
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from constructs import Construct
import prebid_server.stack_constants as stack_constants

ELB_METRICS_NAMESPACE = "AWS/ApplicationELB"


class ECSServiceConstruct(Construct):
    def __init__(
            self,
            scope,
            id,
            stack_params,
            prebid_vpc,
            prebid_cluster,
            prebid_task_definition,
            prebid_task_subnets,
            prebid_container,
            prebid_fs,
    ) -> None:
        """
        This construct creates EFS resources.
        """
        super().__init__(scope, id)

        fargate_service = ecs.FargateService(
            self,
            "PrebidFargateService",
            cluster=prebid_cluster,
            task_definition=prebid_task_definition,
            vpc_subnets=ec2.SubnetSelection(subnets=prebid_task_subnets),
            enable_ecs_managed_tags=True,  # Enable ECS managed tags
            propagate_tags=ecs.PropagatedTagSource.TASK_DEFINITION,
            capacity_provider_strategies=[
                ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE",
                    weight=stack_constants.FARGATE_RESERVED_WEIGHT,
                ),
                ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE_SPOT",
                    weight=stack_params.spot_instance_weight.value_as_number,
                ),
            ],
        )

        # Store the service name for use in metrics
        self.service_name = fargate_service.service_name

        self.alb_target_group = elbv2.ApplicationTargetGroup(
            self,
            "ALBTargetGroup",
            port=80,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            targets=[
                fargate_service.load_balancer_target(
                    container_name=prebid_container.container_name,
                    container_port=prebid_container.container_port)
            ],
            vpc=prebid_vpc,
        )

        # Suppress cfn_guard warning about open egress in the Fargate service security group because Prebid Server containers require open egress in order to connect to demand partners.
        fargate_service_security_group = fargate_service.connections.security_groups[0]
        security_group_l1_construct = fargate_service_security_group.node.find_child(id='Resource')
        security_group_l1_construct.add_metadata("guard", {
            'SuppressedRules': ['EC2_SECURITY_GROUP_EGRESS_OPEN_TO_WORLD_RULE',
                                'SECURITY_GROUP_EGRESS_ALL_PROTOCOLS_RULE']})

        # Allow traffic to/from EFS
        fargate_service.connections.allow_from(
            prebid_fs, ec2.Port.tcp(stack_constants.EFS_PORT)
        )
        fargate_service.connections.allow_to(
            prebid_fs, ec2.Port.tcp(stack_constants.EFS_PORT)
        )

        # Add health check
        self.alb_target_group.configure_health_check(
            path=stack_constants.HEALTH_PATH,
            interval=Duration.seconds(stack_constants.HEALTH_CHECK_INTERVAL_SECS),
            timeout=Duration.seconds(stack_constants.HEALTH_CHECK_TIMEOUT_SECS),
        )

        self.scalable_target = fargate_service.auto_scale_task_count(
            min_capacity=stack_params.ecs_task_min_capacity.value_as_number,
            max_capacity=stack_params.ecs_task_max_capacity.value_as_number,
        )

        scale_cooldown = {
            "scale_in_cooldown": Duration.seconds(stack_constants.SCALE_IN_COOLDOWN_SECS),
            "scale_out_cooldown": Duration.seconds(stack_constants.SCALE_OUT_COOLDOWN_SECS)
        }

        self.scale_cooldown = scale_cooldown
        
        # Initialize scaling policies as None
        self.cpu_scaling_policy = None
        self.memory_scaling_policy = None
        self.alb_request_scaling_policy = None

        # Create a new security group for the internal ALB
        internal_alb_sg = ec2.SecurityGroup(
            self,
            "InternalPrebidALBSecurityGroup",
            vpc=prebid_vpc,
            description="Security group for internal Prebid ALB",
            allow_all_outbound=True
        )
        # Allow inbound traffic on port 80 from Prebid Fargate service
        internal_alb_sg.add_ingress_rule(
            peer=ec2.Peer.security_group_id(fargate_service.connections.security_groups[0].security_group_id),
            connection=ec2.Port.tcp(80),
            description="Allow HTTP traffic only from Prebid Fargate service"
        )
        internal_alb_sg.node.default_child.add_metadata("guard", {
            'SuppressedRules': ['EC2_SECURITY_GROUP_INGRESS_OPEN_TO_WORLD_RULE']}
        )
        
        # Create the new internal ALB
        self.internal_prebid_alb = elbv2.ApplicationLoadBalancer(
            self,
            "InternalPrebidALB",
            vpc=prebid_vpc,
            internet_facing=False,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_group=internal_alb_sg
        )
        self.internal_prebid_alb.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['ELBV2_ACCESS_LOGGING_RULE']})

        # Create HTTP listener for internal ALB
        self.internal_http_listener = self.internal_prebid_alb.add_listener(
            "InternalHTTPListener",
            port=80,
            open=False,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=401, content_type="text/plain",
                message_body="Unauthorized")
        )
        self.internal_http_listener.node.find_child(id='Resource').add_metadata("guard", {
            'SuppressedRules': ['ELBV2_LISTENER_PROTOCOL_RULE', 'ELBV2_LISTENER_SSL_POLICY_RULE']})

        # Allow ECS tasks to access the internal ALB
        fargate_service.connections.security_groups[0].add_egress_rule(
            peer=internal_alb_sg,
            connection=ec2.Port.tcp(80),
            description="Allow ECS tasks to access internal ALB"
        )

    def add_cpu_scaling(self):
        """
        Adds CPU utilization based scaling policy to the service.
        """
        if not self.cpu_scaling_policy:
            self.cpu_scaling_policy = self.scalable_target.scale_on_cpu_utilization(
                "FargateServiceCpuScaling",
                target_utilization_percent=stack_constants.CPU_TARGET_UTILIZATION_PCT,
                **self.scale_cooldown
            )
    
    def add_memory_scaling(self):
        """
        Adds memory utilization based scaling policy to the service.
        """
        if not self.memory_scaling_policy:
            self.memory_scaling_policy = self.scalable_target.scale_on_memory_utilization(
                "FargateServiceMemoryScaling",
                target_utilization_percent=stack_constants.MEMORY_TARGET_UTILIZATION_PCT,
                **self.scale_cooldown
            )
    
    def add_alb_request_count_scaling(self, target_group, requests_per_target):
        """
        Adds an ALB request count based scaling policy to the service.
        
        Args:
            target_group: The ALB target group to monitor for request count
            requests_per_target: The target number of requests per target
        """
        if not self.alb_request_scaling_policy:
            self.alb_request_scaling_policy = self.scalable_target.scale_on_request_count(
                "FargateServiceRequestCountScaling",
                requests_per_target=requests_per_target,
                target_group=target_group,
                **self.scale_cooldown
            )
