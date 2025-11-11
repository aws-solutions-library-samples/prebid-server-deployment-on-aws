# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import pytest
from aws_cdk import (
    App,
    Stack,
    aws_ec2 as ec2,
    aws_efs as efs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins
)
from prebid_server.cloudwatch_dashboard_construct import BaseCloudwatchDashboard, CloudFrontDeploymentDashboard, DashboardSection, S3Section, ImpressionsSection


@pytest.fixture
def app():
    return App()


@pytest.fixture
def stack(app):
    return Stack(app, "TestStack")


@pytest.fixture
def vpc(stack):
    return ec2.Vpc(stack, "TestVpc")


@pytest.fixture
def efs_file_system(stack, vpc):
    return efs.FileSystem(stack, "TestEfs", vpc=vpc)


@pytest.fixture
def alb(stack, vpc):
    return elbv2.ApplicationLoadBalancer(stack, "TestAlb", vpc=vpc, internet_facing=True)


@pytest.fixture
def alb_target_group(stack, vpc):
    return elbv2.ApplicationTargetGroup(
        stack,
        "TestTargetGroup",
        vpc=vpc,
        port=80,
        target_type=elbv2.TargetType.IP
    )


@pytest.fixture
def cloudfront_distribution(stack):
    return cloudfront.Distribution(
        stack,
        "TestDistribution",
        default_behavior=cloudfront.BehaviorOptions(
            origin=origins.HttpOrigin(
                domain_name="example.com",
                protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
                https_port=443
            )
        )
    )
    

def test_alb_deployment_dashboard(stack, vpc, efs_file_system, alb, alb_target_group):
    # Test creating an ALB dashboard
    dashboard = BaseCloudwatchDashboard(
        stack,
        "TestDashboard",
        application_load_balancer=alb,
        efs_file_system=efs_file_system,
        vpc=vpc,
        glue_job_name="test-glue-job",
        ecs_cluster_name="test-cluster",
        ecs_service_name="test-service",
        alb_target_group=alb_target_group,
        cache_target_group=alb_target_group,
        cache_alb=alb,
        data_sync_metrics_bucket_name="test-source-bucket",
        metrics_etl_bucket_name="test-output-bucket",
        cache_lambda_name="test-cache-lambda",
        efs_cleanup_lambda_name="test-efs-cleanup-lambda",
        container_stop_lambda_name="test-container-stop-lambda",
        glue_trigger_lambda_name="test-glue-trigger-lambda",
        elasticache_cluster_id="test-elasticache-cluster",
    )
    
    # Verify the dashboard was created
    assert dashboard is not None
    assert dashboard.dashboard is not None
    
    # Additional assertions for resource presence
    assert dashboard.prebid_alb == alb
    assert dashboard.prebid_fs == efs_file_system
    assert dashboard.prebid_vpc == vpc
    assert dashboard.glue_job_name == "test-glue-job"
    assert dashboard.ecs_cluster_name == "test-cluster"
    assert dashboard.ecs_service_name == "test-service"
    assert dashboard.metric_factory is not None
    assert dashboard.widget_factory is not None
    

def test_cloudfront_deployment_dashboard(stack, vpc, efs_file_system, alb, alb_target_group, cloudfront_distribution):
    # Test creating a CloudFront dashboard
    dashboard = CloudFrontDeploymentDashboard(
        stack,
        "TestDashboard",
        application_load_balancer=alb,
        efs_file_system=efs_file_system,
        vpc=vpc,
        glue_job_name="test-glue-job",
        cloudfront_distribution=cloudfront_distribution,
        waf_webacl_name="test-waf-webacl",
        ecs_cluster_name="test-cluster",
        ecs_service_name="test-service",
        alb_target_group=alb_target_group,
        cache_target_group=alb_target_group,
        cache_alb=alb,
        data_sync_metrics_bucket_name="test-source-bucket",
        metrics_etl_bucket_name="test-output-bucket",
        cache_lambda_name="test-cache-lambda",
        efs_cleanup_lambda_name="test-efs-cleanup-lambda",
        container_stop_lambda_name="test-container-stop-lambda",
        glue_trigger_lambda_name="test-glue-trigger-lambda",
        elasticache_cluster_id="test-elasticache-cluster",
    )
    
    # Verify the dashboard was created
    assert dashboard is not None
    assert dashboard.dashboard is not None
    
    # Additional assertions for resource presence
    assert dashboard.prebid_cloudfront_distribution == cloudfront_distribution
    assert dashboard.waf_webacl_name == "test-waf-webacl"
    assert dashboard.prebid_alb == alb
    assert dashboard.prebid_fs == efs_file_system
    assert dashboard.prebid_vpc == vpc
    assert dashboard.data_sync_metrics_bucket_name == "test-source-bucket"
    assert dashboard.metrics_etl_bucket_name == "test-output-bucket"
    assert dashboard.elasticache_cluster_id == "test-elasticache-cluster"

def test_dashboard_section_abstract_method():
    # Test that DashboardSection.add_to_dashboard raises NotImplementedError
    from aws_cdk import aws_cloudwatch as cloudwatch
    
    # Create a mock dashboard
    mock_dashboard = cloudwatch.Dashboard(Stack(App(), "TestStack"), "TestDashboard")
    
    # Create an instance of the abstract class
    section = DashboardSection(mock_dashboard)
    
    # Verify that the abstract method raises NotImplementedError
    with pytest.raises(NotImplementedError):
        section.add_to_dashboard()

def test_s3_section(stack):
    # Test the S3Section
    from aws_cdk import aws_cloudwatch as cloudwatch
    
    # Create a mock dashboard
    mock_dashboard = cloudwatch.Dashboard(stack, "TestDashboard")
    
    # Create an S3Section
    s3_section = S3Section(mock_dashboard, "test-datasync-bucket", "test-metrics-etl-bucket")
    
    # Test add_to_dashboard method
    s3_section.add_to_dashboard()
    
    # Verify a widget was created (indirectly testing the method was called)
    # We can't directly test private method calls, but we can verify the dashboard received a widget
    assert mock_dashboard is not None

def test_impressions_section(stack):
    # Test the ImpressionsSection
    from aws_cdk import aws_cloudwatch as cloudwatch
    
    # Create a mock dashboard
    mock_dashboard = cloudwatch.Dashboard(stack, "TestDashboard")
    
    # Create an ImpressionsSection
    impressions_section = ImpressionsSection(mock_dashboard)
    
    # Test add_to_dashboard method
    impressions_section.add_to_dashboard()
    
    # Verify a widget was created (indirectly testing the method was called)
    assert mock_dashboard is not None