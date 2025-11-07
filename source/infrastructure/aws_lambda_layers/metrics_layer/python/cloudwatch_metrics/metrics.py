# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime

from aws_solutions.core.helpers import get_service_client


class Metrics:
    def __init__(self, metrics_namespace, resource_prefix, logger):
        self.metrics_namespace = metrics_namespace
        self.resource_prefix = resource_prefix
        self.logger = logger

    def put_metrics_count_value_1(self, metric_name):
        self.logger.info(
            f"Recording 1 (count) for metric {metric_name} in CloudWatch namespace {self.metrics_namespace}")
        cloudwatch_client = get_service_client('cloudwatch')

        cloudwatch_client.put_metric_data(
            Namespace=self.metrics_namespace,
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Dimensions': [{'Name': 'stack-name', 'Value': self.resource_prefix}],
                    'Value': 1,
                    'Unit': 'Count',
                    "Timestamp": datetime.utcnow()
                }
            ]
        )
        
    def put_metrics_count_value_custom(self, metric_name, value):
        self.logger.info(
            f"Recording {value} for metric {metric_name} in CloudWatch namespace {self.metrics_namespace}")
        cloudwatch_client = get_service_client('cloudwatch')

        cloudwatch_client.put_metric_data(
            Namespace=self.metrics_namespace,
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Dimensions': [{'Name': 'stack-name', 'Value': self.resource_prefix}],
                    'Value': value,
                    'Unit': 'Count',
                    "Timestamp": datetime.utcnow()
                }
            ]
        )
