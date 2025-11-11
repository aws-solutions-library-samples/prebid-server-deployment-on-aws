# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

# Path to custom resources for the CDK stack
CUSTOM_RESOURCES_PATH = Path(__file__).absolute().parents[1] / "custom_resources"

# HTTP header names for security and caching
X_SECRET_HEADER_NAME = "X-Header-Secret"  # Custom header for authentication

# VPC and networking configuration
PVT_SUBNET_NAME = "Prebid-Private"  # Name for private subnets
PUB_SUBNET_NAME = "Prebid-Public"   # Name for public subnets
VPC_CIDR = "10.8.0.0/16"            # CIDR block for the VPC
CIDR_MASK = 20                       # Subnet mask for subnet CIDRs
MAX_AZS = 2                          # Maximum number of Availability Zones to use
NAT_GATEWAYS = 2                     # Number of NAT Gateways for private subnet internet access

# Container configuration
CONTAINER_PORT = 8443               # Port exposed by the container
MEMORY_LIMIT_MIB = 4096             # Memory limit for the container in MiB
VCPU = 1024                         # vCPU units for the container (1024 = 1 vCPU)

# Health check configuration
HEALTH_URL_DOMAIN = "https://localhost:" + str(CONTAINER_PORT)
HEALTH_PATH = "/status"
HEALTH_ENDPOINT = HEALTH_URL_DOMAIN + HEALTH_PATH
HEALTH_CHECK_INTERVAL_SECS = 60     # Interval between health checks
HEALTH_CHECK_TIMEOUT_SECS = 5       # Timeout for health check requests

# EFS configuration for persistent storage
EFS_VOLUME_NAME = "prebid-efs-volume"  # Name of the EFS volume
EFS_PORT = 2049                        # Standard NFS port for EFS
EFS_MOUNT_PATH = "/mnt/efs"            # Mount path in the container
EFS_METRICS = "metrics"                # Directory for metrics data
EFS_LOGS = "logs"                      # Directory for logs data
EFS_ANALYTICS = "analytics"            # Directory for analytics data

# Auto-scaling target utilization thresholds
CPU_TARGET_UTILIZATION_PCT = 66      # Target CPU utilization percentage
MEMORY_TARGET_UTILIZATION_PCT = 50   # Target memory utilization percentage


"""
Auto-scaling cooldown periods were determined by analyzing ECS container logs.
Application startup times were extracted using regex pattern 'Started Application in (\d+\.\d+) seconds'
from log entries like: "Started Application in 57.529 seconds (process running for 59.231)".

Analysis of production logs showed:
- Average application startup time: 55.74 seconds
- P95 application startup time: 69.54 seconds

Based on these measurements:
- SCALE_IN_COOLDOWN_SECS is set to P95 startup time + 30s buffer (100s total)
  to ensure new containers are fully operational before scaling in again.
- SCALE_OUT_COOLDOWN_SECS is set to 60s to quickly respond to sudden traffic spikes.
"""
SCALE_OUT_COOLDOWN_SECS = 60  # Optimized for rapid response to traffic spikes
SCALE_IN_COOLDOWN_SECS = 100  # Based on P95 container startup time + buffer

# Task capacity limits
TASK_MIN_CAPACITY = 2    # Minimum number of tasks to maintain (provides redundancy)
TASK_MAX_CAPACITY = 300  # Maximum number of tasks allowed to scale to

# Request handling capacity
REQUESTS_PER_TARGET_THRESHOLD = 5000  # Maximum theoretical requests per target

# Instance weighting for capacity providers
SPOT_INSTANCE_WEIGHT = 1     # Relative capacity weight for Spot instances
FARGATE_RESERVED_WEIGHT = 1  # Relative capacity weight for Fargate reserved instances

# DataSync configuration for data transfer
DATASYNC_METRICS_SCHEDULE = "cron(30 * * * ? *)"  # Hourly on the half hour
DATASYNC_ANALYTICS_SCHEDULE = "cron(30 * * * ? *)"  # Hourly on the half hour
DATASYNC_REPORT_LIFECYCLE_DAYS = 1  # Number of days to retain DataSync reports

# AWS Glue configuration for data processing
GLUE_MAX_CONCURRENT_RUNS = 10       # Maximum number of concurrent Glue job runs
GLUE_TIMEOUT_MINS = 120             # Timeout for Glue jobs in minutes
GLUE_ATHENA_OUTPUT_LIFECYCLE_DAYS = 1  # Number of days to retain Athena query results

# CloudFront configuration
# CloudFront managed headers policy CORS-with-preflight-and-SecurityHeadersPolicy
RESPONSE_HEADERS_POLICY_ID = "eaab4381-ed33-4a86-88ca-d9558dc6cd63"

# CloudWatch monitoring configuration
CLOUDWATCH_ALARM_TYPE = "AWS::CloudWatch::Alarm"  # CloudWatch alarm resource type
CLOUDWATCH_ALARM_NAMESPACE = "AWS/ApplicationELB"  # Namespace for ALB metrics

# Anomaly detection with 2 standard deviations (medium sensitivity band)
ANOMALY_DETECTION_BAND_2 = "ANOMALY_DETECTION_BAND(m1, 2)"

# AWS service namespaces
CLOUDFRONT_NAMESPACE = "AWS/CloudFront"  # CloudFront metrics namespace
RESOURCE_NAMESPACE = "aws:ResourceAccount"  # Resource account namespace

# Solution metadata
SOLUTION_APPLICATION_TYPE = "AWS-Solutions"  # Application type tag for AWS Solutions
