# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from typing import List, Dict, Any, Tuple, Optional
from aws_cdk import (
    Aws,
    aws_cloudwatch as cloudwatch,
    aws_elasticloadbalancingv2 as elbv2,
    aws_efs as efs,
    aws_ec2 as ec2,
    aws_cloudfront as cloudfront,
    CfnOutput,
    Duration,
)
from aws_cdk.aws_cloudwatch import Color, Unit
from constructs import Construct

import prebid_server.stack_constants as stack_constants

# Global constants for dashboard widget dimensions
WIDGET_WIDTH: int = 8
WIDGET_HEIGHT: int = 6  # Default height for most widgets
ALARM_WIDGET_HEIGHT: int = 12  # Taller height for alarm status widget
HALF_ROW_WIDTH: int = 12  # Width for widgets that take half a row
FULL_ROW_WIDTH: int = 24  # Width for widgets that take a full row
ELASTICACHE_WIDGET_WIDTH: int = 8  # Width for ElastiCache widgets (3 per row)
ELASTICACHE_WIDGET_HEIGHT: int = 8  # Height for ElastiCache widgets

# Constants for widgets
NATGW_NAMESPACE: str = "AWS/NATGateway"
ELASTICACHE_NAMESPACE: str = "AWS/ElastiCache"
LAMBDA_NAMESPACE: str = "AWS/Lambda"

# Common metric properties
DEFAULT_PERIOD: Duration = Duration.minutes(1)
DEFAULT_STATISTIC: str = "Sum"

class MetricFactory:
    """Factory class for creating CloudWatch metrics with common defaults."""
    
    @staticmethod
    def create_metric(
        namespace: str,
        metric_name: str,
        dimensions_map: Dict[str, str],
        label: Optional[str] = None,
        statistic: str = DEFAULT_STATISTIC,
        period: Duration = DEFAULT_PERIOD,
        unit: Optional[Unit] = None,
        region: Optional[str] = None,
        color: Optional[str] = None,
    ) -> cloudwatch.Metric:
        """Create a CloudWatch metric with common defaults."""
        return cloudwatch.Metric(
            namespace=namespace,
            metric_name=metric_name,
            dimensions_map=dimensions_map,
            statistic=statistic,
            period=period,
            label=label,
            unit=unit,
            region=region,
            color=color,
        )

class WidgetFactory:
    """Factory class for creating CloudWatch dashboard widgets."""
    
    @staticmethod
    def create_graph_widget(
        title: str,
        metrics: List[cloudwatch.IMetric],
        width: int = WIDGET_WIDTH,
        height: int = WIDGET_HEIGHT,
        region: Optional[str] = None,
    ) -> cloudwatch.GraphWidget:
        """Create a GraphWidget with common defaults."""
        return cloudwatch.GraphWidget(
            title=title,
            left=metrics,
            width=width,
            height=height,
            region=region,
        )

class DashboardSection:
    """Base class for dashboard sections."""
    
    def __init__(self, dashboard: cloudwatch.Dashboard) -> None:
        self.dashboard = dashboard
        self.metric_factory = MetricFactory()
        self.widget_factory = WidgetFactory()
    
    def add_to_dashboard(self) -> None:
        """Add the section's widgets to the dashboard."""
        raise NotImplementedError

class ALBSection(DashboardSection):
    """Dashboard section for ALB metrics."""
    
    def __init__(
        self,
        dashboard: cloudwatch.Dashboard,
        alb: elbv2.ApplicationLoadBalancer,
        target_group: elbv2.ApplicationTargetGroup,
        is_public: bool = True,
    ) -> None:
        super().__init__(dashboard)
        self.alb = alb
        self.target_group = target_group
        self.is_public = is_public
        self.prefix = "Public" if is_public else "Internal Cache"
    
    def add_to_dashboard(self) -> None:
        request_count = self._create_request_count_widget()
        http_codes = self._create_http_codes_widget()
        bytes_widget = self._create_bytes_widget()
        
        self.dashboard.add_widgets(request_count, http_codes, bytes_widget)
    
    def _create_request_count_widget(self) -> cloudwatch.GraphWidget:
        metrics = [
            self.metric_factory.create_metric(
                namespace=stack_constants.CLOUDWATCH_ALARM_NAMESPACE,
                metric_name="RequestCount",
                dimensions_map={"LoadBalancer": self.alb.load_balancer_full_name},
                label="Total Requests",
                unit=Unit.COUNT,
            ),
            self.metric_factory.create_metric(
                namespace=stack_constants.CLOUDWATCH_ALARM_NAMESPACE,
                metric_name="RequestCountPerTarget",
                dimensions_map={
                    "LoadBalancer": self.alb.load_balancer_full_name,
                    "TargetGroup": self.target_group.target_group_full_name,
                },
                label="Requests Per Target",
                unit=Unit.COUNT,
            ),
        ]
        return self.widget_factory.create_graph_widget(
            title=f"{self.prefix} ALB Request Count",
            metrics=metrics,
        )
    
    def _create_http_codes_widget(self) -> cloudwatch.GraphWidget:
        metrics = []
        for code, color in [
            ("2XX", Color.GREEN),
            ("3XX", Color.BLUE),
            ("4XX", Color.ORANGE),
            ("5XX", Color.RED),
        ]:
            metrics.append(
                self.metric_factory.create_metric(
                    namespace=stack_constants.CLOUDWATCH_ALARM_NAMESPACE,
                    metric_name=f"HTTPCode_Target_{code}_Count",
                    dimensions_map={"LoadBalancer": self.alb.load_balancer_full_name},
                    unit=Unit.COUNT,
                    color=color,
                )
            )
        return self.widget_factory.create_graph_widget(
            title=f"{self.prefix} ALB HTTP Target Status",
            metrics=metrics,
        )
    
    def _create_bytes_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title=f"{self.prefix} ALB Bytes",
            metrics=[
                self.metric_factory.create_metric(
                    namespace=stack_constants.CLOUDWATCH_ALARM_NAMESPACE,
                    metric_name="ProcessedBytes",
                    dimensions_map={"LoadBalancer": self.alb.load_balancer_full_name},
                    label="Processed Bytes",
                    unit=Unit.BYTES,
                )
            ],
            region=Aws.REGION,
        )

class NATSection(DashboardSection):
    """Dashboard section for NAT Gateway metrics."""
    
    def __init__(self, dashboard: cloudwatch.Dashboard, vpc: ec2.Vpc) -> None:
        super().__init__(dashboard)
        self.vpc = vpc
    
    def add_to_dashboard(self) -> None:
        connections = self._create_connections_widget()
        bytes_widget = self._create_bytes_widget()
        self.dashboard.add_widgets(connections, bytes_widget)
    
    def _create_connections_widget(self) -> cloudwatch.GraphWidget:
        metrics = []
        for i, subnet in enumerate(self.vpc.public_subnets):
            metrics.append(
                self.metric_factory.create_metric(
                    namespace=NATGW_NAMESPACE,
                    metric_name="ActiveConnectionCount",
                    dimensions_map={
                        "NatGatewayId": subnet.node.find_child("NATGateway").ref,
                    },
                    label=f"Active Connections (NAT {i+1})",
                    unit=Unit.COUNT,
                )
            )
        return self.widget_factory.create_graph_widget(
            title="NAT Gateway Connections",
            metrics=metrics,
            width=HALF_ROW_WIDTH,
        )
    
    def _create_bytes_widget(self) -> cloudwatch.GraphWidget:
        metrics = []
        for i, subnet in enumerate(self.vpc.public_subnets):
            metrics.extend([
                self.metric_factory.create_metric(
                    namespace=NATGW_NAMESPACE,
                    metric_name="BytesInFromDestination",
                    dimensions_map={
                        "NatGatewayId": subnet.node.find_child("NATGateway").ref,
                    },
                    label=f"Bytes In From Destination (NAT {i+1})",
                    unit=Unit.BYTES,
                ),
                self.metric_factory.create_metric(
                    namespace=NATGW_NAMESPACE,
                    metric_name="BytesOutToDestination",
                    dimensions_map={
                        "NatGatewayId": subnet.node.find_child("NATGateway").ref,
                    },
                    label=f"Bytes Out To Destination (NAT {i+1})",
                    unit=Unit.BYTES,
                ),
            ])
        return self.widget_factory.create_graph_widget(
            title="NAT Gateway Bytes",
            metrics=metrics,
            width=HALF_ROW_WIDTH,
        )

class LambdaSection(DashboardSection):
    """Dashboard section for Lambda metrics."""
    
    def __init__(
        self,
        dashboard: cloudwatch.Dashboard,
        lambda_names: Dict[str, str],
    ) -> None:
        super().__init__(dashboard)
        self.lambda_names = lambda_names
    
    def add_to_dashboard(self) -> None:
        invocations = self._create_invocations_widget()
        errors = self._create_errors_widget()
        duration = self._create_duration_widget()
        self.dashboard.add_widgets(invocations, errors, duration)
    
    def _create_invocations_widget(self) -> cloudwatch.GraphWidget:
        metrics = []
        for name, label in self.lambda_names.items():
            metrics.append(
                self.metric_factory.create_metric(
                    namespace=LAMBDA_NAMESPACE,
                    metric_name="Invocations",
                    dimensions_map={"FunctionName": name},
                    label=label,
                    unit=Unit.COUNT,
                )
            )
        return self.widget_factory.create_graph_widget(
            title="Lambda Function Invocations",
            metrics=metrics,
            width=WIDGET_WIDTH,
        )
    
    def _create_errors_widget(self) -> cloudwatch.GraphWidget:
        metrics = []
        for name, label in self.lambda_names.items():
            metrics.append(
                self.metric_factory.create_metric(
                    namespace=LAMBDA_NAMESPACE,
                    metric_name="Errors",
                    dimensions_map={"FunctionName": name},
                    label=label,
                    unit=Unit.COUNT,
                )
            )
        return self.widget_factory.create_graph_widget(
            title="Lambda Function Errors",
            metrics=metrics,
            width=WIDGET_WIDTH,
        )
    
    def _create_duration_widget(self) -> cloudwatch.GraphWidget:
        metrics = []
        for name, label in self.lambda_names.items():
            # Add Average duration metric
            metrics.append(
                self.metric_factory.create_metric(
                    namespace=LAMBDA_NAMESPACE,
                    metric_name="Duration",
                    dimensions_map={"FunctionName": name},
                    label=f"{label} (Avg)",
                    statistic="Average",
                    unit=Unit.MILLISECONDS,
                )
            )
            # Add Maximum duration metric
            metrics.append(
                self.metric_factory.create_metric(
                    namespace=LAMBDA_NAMESPACE,
                    metric_name="Duration",
                    dimensions_map={"FunctionName": name},
                    label=f"{label} (Max)",
                    statistic="Maximum",
                    unit=Unit.MILLISECONDS,
                )
            )
        return self.widget_factory.create_graph_widget(
            title="Lambda Function Duration",
            metrics=metrics,
            width=WIDGET_WIDTH,
        )

class ECSSection(DashboardSection):
    """Dashboard section for ECS metrics."""
    
    def __init__(
        self,
        dashboard: cloudwatch.Dashboard,
        cluster_name: str,
        service_name: str,
    ) -> None:
        super().__init__(dashboard)
        self.cluster_name = cluster_name
        self.service_name = service_name
    
    def add_to_dashboard(self) -> None:
        task_count = self._create_task_count_widget()
        cpu_utilization = self._create_cpu_utilization_widget()
        memory_utilization = self._create_memory_utilization_widget()
        
        self.dashboard.add_widgets(task_count, cpu_utilization, memory_utilization)
    
    def _create_task_count_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="ECS Task Count",
            metrics=[
                self.metric_factory.create_metric(
                    namespace="ECS/ContainerInsights",
                    metric_name="RunningTaskCount",
                    dimensions_map={
                        "ClusterName": self.cluster_name,
                        "ServiceName": self.service_name,
                    },
                    statistic="Maximum",
                    unit=Unit.COUNT,
                )
            ],
        )
        
    def _create_cpu_utilization_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="ECS CPU Utilization",
            metrics=[
                self.metric_factory.create_metric(
                    namespace="AWS/ECS",
                    metric_name="CPUUtilization",
                    dimensions_map={
                        "ClusterName": self.cluster_name,
                        "ServiceName": self.service_name,
                    },
                    statistic="Average",
                    label="Average",
                    unit=Unit.PERCENT,
                ),
                self.metric_factory.create_metric(
                    namespace="AWS/ECS",
                    metric_name="CPUUtilization",
                    dimensions_map={
                        "ClusterName": self.cluster_name,
                        "ServiceName": self.service_name,
                    },
                    statistic="Maximum",
                    label="Maximum",
                    unit=Unit.PERCENT,
                )
            ],
        )
        
    def _create_memory_utilization_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="ECS Memory Utilization",
            metrics=[
                self.metric_factory.create_metric(
                    namespace="AWS/ECS",
                    metric_name="MemoryUtilization",
                    dimensions_map={
                        "ClusterName": self.cluster_name,
                        "ServiceName": self.service_name,
                    },
                    statistic="Average",
                    unit=Unit.PERCENT,
                )
            ],
        )

class EFSSection(DashboardSection):
    """Dashboard section for EFS metrics."""
    
    def __init__(self, dashboard: cloudwatch.Dashboard, file_system: efs.FileSystem) -> None:
        super().__init__(dashboard)
        self.file_system = file_system
    
    def add_to_dashboard(self) -> None:
        io_metrics = self._create_io_metrics_widget()
        storage_metrics = self._create_storage_metrics_widget()
        self.dashboard.add_widgets(io_metrics, storage_metrics)
    
    def _create_io_metrics_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="EFS Data and Metadata IO",
            metrics=[
                # Data IO metrics
                self.metric_factory.create_metric(
                    namespace="AWS/EFS",
                    metric_name="DataReadIOBytes",
                    dimensions_map={"FileSystemId": self.file_system.file_system_id},
                    label="Data Read",
                    unit=Unit.BYTES,
                ),
                self.metric_factory.create_metric(
                    namespace="AWS/EFS",
                    metric_name="DataWriteIOBytes",
                    dimensions_map={"FileSystemId": self.file_system.file_system_id},
                    label="Data Write",
                    unit=Unit.BYTES,
                ),
                # Metadata IO metrics
                self.metric_factory.create_metric(
                    namespace="AWS/EFS",
                    metric_name="MetadataIOBytes",
                    dimensions_map={"FileSystemId": self.file_system.file_system_id},
                    label="Metadata IO",
                    unit=Unit.BYTES,
                ),
            ],
            width=HALF_ROW_WIDTH,
        )

    def _create_storage_metrics_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="EFS Storage Usage",
            metrics=[
                self.metric_factory.create_metric(
                    namespace="AWS/EFS",
                    metric_name="StorageBytes",
                    dimensions_map={
                        "FileSystemId": self.file_system.file_system_id,
                        "StorageClass": "Total"
                    },
                    label="Total Storage",
                    unit=Unit.BYTES,
                ),
                self.metric_factory.create_metric(
                    namespace="AWS/EFS",
                    metric_name="StorageBytes",
                    dimensions_map={
                        "FileSystemId": self.file_system.file_system_id,
                        "StorageClass": "Standard"
                    },
                    label="Standard Storage",
                    unit=Unit.BYTES,
                ),
                self.metric_factory.create_metric(
                    namespace="AWS/EFS",
                    metric_name="StorageBytes",
                    dimensions_map={
                        "FileSystemId": self.file_system.file_system_id,
                        "StorageClass": "IA"
                    },
                    label="IA Storage",
                    unit=Unit.BYTES,
                ),
            ],
            width=HALF_ROW_WIDTH,
        )

class ElastiCacheSection(DashboardSection):
    """Dashboard section for ElastiCache metrics."""
    
    def __init__(self, dashboard: cloudwatch.Dashboard, cache_cluster_id: str) -> None:
        super().__init__(dashboard)
        self.cache_cluster_id = cache_cluster_id
    
    def add_to_dashboard(self) -> None:
        hits_misses = self._create_hits_misses_widget()
        curr_items = self._create_curr_items_widget()
        network_bytes = self._create_network_bytes_widget()
        
        self.dashboard.add_widgets(hits_misses, curr_items, network_bytes)
    
    def _create_hits_misses_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="ElastiCache Hits and Misses",
            metrics=[
                self.metric_factory.create_metric(
                    namespace=ELASTICACHE_NAMESPACE,
                    metric_name="CacheHits",
                    dimensions_map={"clusterId": self.cache_cluster_id},
                    label="Cache Hits",
                    statistic="Sum",
                    color=Color.GREEN,
                    unit=Unit.COUNT,
                ),
                self.metric_factory.create_metric(
                    namespace=ELASTICACHE_NAMESPACE,
                    metric_name="CacheMisses",
                    dimensions_map={"clusterId": self.cache_cluster_id},
                    label="Cache Misses",
                    statistic="Sum",
                    color=Color.RED,
                    unit=Unit.COUNT,
                ),
            ],
            width=ELASTICACHE_WIDGET_WIDTH,
            height=ELASTICACHE_WIDGET_HEIGHT,
            region=Aws.REGION,
        )
    
    def _create_curr_items_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="ElastiCache Items",
            metrics=[
                self.metric_factory.create_metric(
                    namespace=ELASTICACHE_NAMESPACE,
                    metric_name="CurrItems",
                    dimensions_map={"clusterId": self.cache_cluster_id},
                    label="Current Items",
                    statistic="Average",
                    unit=Unit.COUNT,
                ),
                self.metric_factory.create_metric(
                    namespace=ELASTICACHE_NAMESPACE,
                    metric_name="CurrVolatileItems",
                    dimensions_map={"clusterId": self.cache_cluster_id},
                    label="Current Volatile Items",
                    statistic="Average",
                    unit=Unit.COUNT,
                ),
            ],
            width=ELASTICACHE_WIDGET_WIDTH,
            height=ELASTICACHE_WIDGET_HEIGHT,
            region=Aws.REGION,
        )
    
    def _create_network_bytes_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="ElastiCache Network Traffic",
            metrics=[
                self.metric_factory.create_metric(
                    namespace=ELASTICACHE_NAMESPACE,
                    metric_name="NetworkBytesIn",
                    dimensions_map={"clusterId": self.cache_cluster_id},
                    label="Network Bytes In",
                    statistic="Sum",
                    unit=Unit.BYTES,
                ),
                self.metric_factory.create_metric(
                    namespace=ELASTICACHE_NAMESPACE,
                    metric_name="NetworkBytesOut",
                    dimensions_map={"clusterId": self.cache_cluster_id},
                    label="Network Bytes Out",
                    statistic="Sum",
                    unit=Unit.BYTES,
                ),
            ],
            width=ELASTICACHE_WIDGET_WIDTH,
            height=ELASTICACHE_WIDGET_HEIGHT,
            region=Aws.REGION,
        )

class S3Section(DashboardSection):
    """Dashboard section for S3 metrics."""
    
    def __init__(
        self,
        dashboard: cloudwatch.Dashboard,
        data_sync_bucket_name: str,
        metrics_etl_bucket_name: str,
    ) -> None:
        super().__init__(dashboard)
        self.data_sync_bucket_name = data_sync_bucket_name
        self.metrics_etl_bucket_name = metrics_etl_bucket_name
    
    def add_to_dashboard(self) -> None:
        storage_widget = self._create_storage_widget()
        self.dashboard.add_widgets(storage_widget)
    
    def _create_storage_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="S3 Bucket Storage",
            metrics=[
                self.metric_factory.create_metric(
                    namespace="AWS/S3",
                    metric_name="BucketSizeBytes",
                    dimensions_map={
                        "BucketName": self.data_sync_bucket_name,
                        "StorageType": "StandardStorage"
                    },
                    label="Pre-ETL Metrics Bucket",
                    unit=Unit.BYTES,
                    region=Aws.REGION,
                    period=Duration.days(1),  # required for S3 metrics
                ),
                self.metric_factory.create_metric(
                    namespace="AWS/S3",
                    metric_name="BucketSizeBytes",
                    dimensions_map={
                        "BucketName": self.metrics_etl_bucket_name,
                        "StorageType": "StandardStorage"
                    },
                    label="Post-ETL Metrics Bucket",
                    unit=Unit.BYTES,
                    region=Aws.REGION,
                    period=Duration.days(1),  # required for S3 metrics
                ),
            ],
            width=HALF_ROW_WIDTH,
            region=Aws.REGION,
        )

class ImpressionsSection(DashboardSection):
    """Dashboard section for auction and impression metrics."""
    
    def add_to_dashboard(self) -> None:
        impressions_widget = self._create_impressions_widget()
        self.dashboard.add_widgets(impressions_widget)
    
    def _create_impressions_widget(self) -> cloudwatch.GraphWidget:
        return self.widget_factory.create_graph_widget(
            title="Auctions",
            metrics=[
                self.metric_factory.create_metric(
                    namespace=f"{Aws.STACK_NAME}-metrics",
                    metric_name="AuctionRequests",
                    dimensions_map={"stack-name": Aws.STACK_NAME},
                    label="Auction Requests",
                    period=Duration.minutes(1),
                    unit=Unit.COUNT,
                ),
                self.metric_factory.create_metric(
                    namespace=f"{Aws.STACK_NAME}-metrics",
                    metric_name="ImpsRequested",
                    dimensions_map={"stack-name": Aws.STACK_NAME},
                    label="Impressions Requested",
                    period=Duration.minutes(1),
                    unit=Unit.COUNT,
                ),
            ],
            width=HALF_ROW_WIDTH,
            region=Aws.REGION,
        )

class BaseCloudwatchDashboard(Construct):
    """Base class for creating CloudWatch dashboards with standard AWS service metrics."""
    
    def __init__(   
        self, # NOSONAR
        scope: Construct,
        id: str,
        application_load_balancer: elbv2.ApplicationLoadBalancer,
        efs_file_system: efs.FileSystem,
        vpc: ec2.Vpc,
        glue_job_name: str,
        ecs_cluster_name: str,
        ecs_service_name: str,
        alb_target_group: elbv2.ApplicationTargetGroup,
        cache_target_group: elbv2.ApplicationTargetGroup,
        cache_alb: elbv2.ApplicationLoadBalancer,
        data_sync_metrics_bucket_name: str,
        metrics_etl_bucket_name: str,
        cache_lambda_name: str,
        efs_cleanup_lambda_name: str,
        container_stop_lambda_name: str,
        glue_trigger_lambda_name: str,
        elasticache_cluster_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)
        
        # Initialize factories
        self.metric_factory = MetricFactory()
        self.widget_factory = WidgetFactory()
        
        # Store references to resources
        self.prebid_alb = application_load_balancer
        self.prebid_fs = efs_file_system
        self.prebid_vpc = vpc
        self.glue_job_name = glue_job_name
        self.ecs_cluster_name = ecs_cluster_name
        self.ecs_service_name = ecs_service_name
        self.alb_target_group = alb_target_group
        self.cache_target_group = cache_target_group
        self.cache_alb = cache_alb
        self.data_sync_metrics_bucket_name = data_sync_metrics_bucket_name
        self.metrics_etl_bucket_name = metrics_etl_bucket_name
        self.cache_lambda_name = cache_lambda_name
        self.efs_cleanup_lambda_name = efs_cleanup_lambda_name
        self.container_stop_lambda_name = container_stop_lambda_name
        self.glue_trigger_lambda_name = glue_trigger_lambda_name
        self.elasticache_cluster_id = elasticache_cluster_id
        
        # Create the dashboard
        self.dashboard = cloudwatch.Dashboard(
            self,
            "PrebidDeploymentDashboard",
            dashboard_name=f"Dashboard-{Aws.STACK_NAME}-{Aws.REGION}",
        )
        
        # Add dashboard URL to stack outputs
        CfnOutput(
            self,
            "DashboardUrl",
            value=f"https://{Aws.REGION}.console.aws.amazon.com/cloudwatch/home?region={Aws.REGION}#dashboards:name=Dashboard-{Aws.STACK_NAME}-{Aws.REGION}",
            description="Link to the CloudWatch Dashboard",
        )
        
        # Allow subclasses to add their widgets first
        self._add_custom_widgets()
        
        # Create and add dashboard sections
        self._add_dashboard_sections()
    
    def _add_custom_widgets(self) -> None:
        """Override this method in subclasses to add custom widgets before base widgets"""
        pass
    
    def _add_dashboard_sections(self) -> None:
        """Add all dashboard sections in the desired order."""
        # Add ALB sections
        public_alb_section = ALBSection(
            self.dashboard,
            self.prebid_alb,
            self.alb_target_group,
            is_public=True,
        )
        public_alb_section.add_to_dashboard()
        
        cache_alb_section = ALBSection(
            self.dashboard,
            self.cache_alb,
            self.cache_target_group,
            is_public=False,
        )
        cache_alb_section.add_to_dashboard()
        
        # Add Lambda section
        lambda_section = LambdaSection(
            self.dashboard,
            {
                self.cache_lambda_name: "Cache",
                self.efs_cleanup_lambda_name: "EFS Cleanup",
                self.container_stop_lambda_name: "Container Stop Logs",
                self.glue_trigger_lambda_name: "Glue Trigger",
            },
        )
        lambda_section.add_to_dashboard()
        
        # Add NAT section
        nat_section = NATSection(self.dashboard, self.prebid_vpc)
        nat_section.add_to_dashboard()
        
        # Add ECS section
        ecs_section = ECSSection(
            self.dashboard,
            self.ecs_cluster_name,
            self.ecs_service_name,
        )
        ecs_section.add_to_dashboard()
        
        # Add EFS section
        efs_section = EFSSection(self.dashboard, self.prebid_fs)
        efs_section.add_to_dashboard()
        
        # Add ElastiCache section
        elasticache_section = ElastiCacheSection(
            self.dashboard,
            self.elasticache_cluster_id,
        )
        elasticache_section.add_to_dashboard()
        
        # Add S3 and Impressions sections on the same row
        s3_section = S3Section(
            self.dashboard,
            self.data_sync_metrics_bucket_name,
            self.metrics_etl_bucket_name,
        )
        impressions_section = ImpressionsSection(self.dashboard)
        
        # Get the widgets from both sections
        s3_widget = s3_section._create_storage_widget()
        impressions_widget = impressions_section._create_impressions_widget()
        
        # Add them to the dashboard in the same row
        self.dashboard.add_widgets(s3_widget, impressions_widget)

class CloudFrontDeploymentDashboard(BaseCloudwatchDashboard):
    """Extended dashboard class that includes CloudFront and WAF metrics."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        application_load_balancer: elbv2.ApplicationLoadBalancer,
        efs_file_system: efs.FileSystem,
        vpc: ec2.Vpc,
        glue_job_name: str,
        ecs_cluster_name: str,
        ecs_service_name: str,
        alb_target_group: elbv2.ApplicationTargetGroup,
        cache_target_group: elbv2.ApplicationTargetGroup,
        cache_alb: elbv2.ApplicationLoadBalancer,
        cloudfront_distribution: cloudfront.Distribution,
        waf_webacl_name: str,
        data_sync_metrics_bucket_name: str,
        metrics_etl_bucket_name: str,
        cache_lambda_name: str,
        efs_cleanup_lambda_name: str,
        container_stop_lambda_name: str,
        glue_trigger_lambda_name: str,
        elasticache_cluster_id: str,
        **kwargs,
    ) -> None:
        self.prebid_cloudfront_distribution = cloudfront_distribution
        self.waf_webacl_name = waf_webacl_name
        
        super().__init__(
            scope,
            id,
            application_load_balancer=application_load_balancer,
            efs_file_system=efs_file_system,
            vpc=vpc,
            glue_job_name=glue_job_name,
            ecs_cluster_name=ecs_cluster_name,
            ecs_service_name=ecs_service_name,
            alb_target_group=alb_target_group,
            cache_target_group=cache_target_group,
            cache_alb=cache_alb,
            data_sync_metrics_bucket_name=data_sync_metrics_bucket_name,
            metrics_etl_bucket_name=metrics_etl_bucket_name,
            cache_lambda_name=cache_lambda_name,
            efs_cleanup_lambda_name=efs_cleanup_lambda_name,
            container_stop_lambda_name=container_stop_lambda_name,
            glue_trigger_lambda_name=glue_trigger_lambda_name,
            elasticache_cluster_id=elasticache_cluster_id,
            **kwargs,
        )

    def _add_custom_widgets(self) -> None:
        """Add CloudFront and WAF widgets before base widgets."""
        # Create WAF widget
        waf_requests = self.widget_factory.create_graph_widget(
            title="WAF WebACL Requests",
            metrics=[
                self.metric_factory.create_metric(
                    namespace="AWS/WAFV2",
                    metric_name="AllowedRequests",
                    dimensions_map={
                        "WebACL": self.waf_webacl_name,
                        "Rule": "ALL",
                    },
                    label="Allowed Requests",
                    color=Color.GREEN,
                    unit=Unit.COUNT,
                ),
                self.metric_factory.create_metric(
                    namespace="AWS/WAFV2",
                    metric_name="BlockedRequests",
                    dimensions_map={
                        "WebACL": self.waf_webacl_name,
                        "Rule": "ALL",
                    },
                    label="Blocked Requests",
                    color=Color.RED,
                    unit=Unit.COUNT,
                ),
            ],
            region="us-east-1",
        )
        
        # Create CloudFront widgets
        cf_requests = self.widget_factory.create_graph_widget(
            title="CloudFront Requests",
            metrics=[
                self.metric_factory.create_metric(
                    namespace=stack_constants.CLOUDFRONT_NAMESPACE,
                    metric_name="Requests",
                    dimensions_map={
                        "Region": "Global",
                        "DistributionId": self.prebid_cloudfront_distribution.distribution_id,
                    },
                    unit=Unit.COUNT,
                )
            ],
            region="us-east-1",
        )
        
        cf_error_rates = self.widget_factory.create_graph_widget(
            title="CloudFront Error Rates",
            metrics=[
                self.metric_factory.create_metric(
                    namespace=stack_constants.CLOUDFRONT_NAMESPACE,
                    metric_name="4xxErrorRate",
                    dimensions_map={
                        "Region": "Global",
                        "DistributionId": self.prebid_cloudfront_distribution.distribution_id,
                    },
                    statistic="Average",
                    color=Color.ORANGE,
                    unit=Unit.PERCENT,
                ),
                self.metric_factory.create_metric(
                    namespace=stack_constants.CLOUDFRONT_NAMESPACE,
                    metric_name="5xxErrorRate",
                    dimensions_map={
                        "Region": "Global",
                        "DistributionId": self.prebid_cloudfront_distribution.distribution_id,
                    },
                    statistic="Average",
                    color=Color.RED,
                    unit=Unit.PERCENT,
                ),
                self.metric_factory.create_metric(
                    namespace=stack_constants.CLOUDFRONT_NAMESPACE,
                    metric_name="TotalErrorRate",
                    dimensions_map={
                        "Region": "Global",
                        "DistributionId": self.prebid_cloudfront_distribution.distribution_id,
                    },
                    statistic="Average",
                    color=Color.BLUE,
                    unit=Unit.PERCENT,
                ),
            ],
            region="us-east-1",
        )
        
        cf_bytes = self.widget_factory.create_graph_widget(
            title="CloudFront Bytes",
            metrics=[
                self.metric_factory.create_metric(
                    namespace=stack_constants.CLOUDFRONT_NAMESPACE,
                    metric_name="BytesDownloaded",
                    dimensions_map={
                        "Region": "Global",
                        "DistributionId": self.prebid_cloudfront_distribution.distribution_id,
                    },
                    label="Bytes Downloaded",
                    unit=Unit.BYTES,
                ),
                self.metric_factory.create_metric(
                    namespace=stack_constants.CLOUDFRONT_NAMESPACE,
                    metric_name="BytesUploaded",
                    dimensions_map={
                        "Region": "Global",
                        "DistributionId": self.prebid_cloudfront_distribution.distribution_id,
                    },
                    label="Bytes Uploaded",
                    unit=Unit.BYTES,
                ),
            ],
            width=FULL_ROW_WIDTH,
            region="us-east-1",
        )
        
        # Add widgets to dashboard
        self.dashboard.add_widgets(waf_requests, cf_requests, cf_error_rates)
        self.dashboard.add_widgets(cf_bytes)

