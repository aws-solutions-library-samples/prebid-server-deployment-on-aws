# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0


import os
import json
import logging
import requests
from datetime import datetime, timedelta
from aws_solutions.core.helpers import get_service_client

SOLUTION_ID = os.environ["SOLUTION_ID"]
SOLUTION_VERSION = os.environ["SOLUTION_VERSION"]
METRICS_NAMESPACE = os.environ["METRICS_NAMESPACE"]
SEND_ANONYMIZED_DATA = os.environ["SEND_ANONYMIZED_DATA"]
STACK_NAME = os.environ["STACK_NAME"]

SECONDS_IN_A_DAY = 86400

DT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Format log messages like this:
formatter = logging.Formatter("{%(pathname)s:%(lineno)d} %(levelname)s - %(message)s")
handler = logging.StreamHandler()
handler.setFormatter(formatter)
# Clear the default logger before attaching the custom logging handler
# in order to avoid duplicating each log message:
logging.getLogger().handlers.clear()
# Attach the custom logging handler:
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

METRICS_ENDPOINT = "https://metrics.awssolutionsbuilder.com/generic"


class CloudwatchMetricsReport:
    def __init__(self):
        self.cloudwatch_client = get_service_client("cloudwatch")
        self.secrets_manager_client = get_service_client("secretsmanager")
        self.ec2_client = get_service_client("ec2")
        self.timestamp = datetime.utcnow()
        self.end_time = datetime.utcnow()
        self.start_time = self.end_time - timedelta(seconds=SECONDS_IN_A_DAY)
        self.statistics = ["Sum", "Minimum", "Maximum"]
        self.uuid = self.get_uuid()

    @staticmethod
    def data_init():
        return {"Data": {}, "MetricData": {}}

    @staticmethod
    def resolve_dt_time_format(datetime_obj):
        return datetime_obj.strftime(DT_TIME_FORMAT)

    @staticmethod
    def sum_datapoints(datapoints, stat="Sum"):
        if len(datapoints) > 1:
            logger.warning(
                "Got "
                + str(len(datapoints))
                + " datapoints but only expected one datapoint since period is one day and start/end time spans one day."
            )
        total = 0
        for datapoint in datapoints:
            # There should only be one datapoint since period is one day and
            # start/end time spans one day, but if there is more than one datapoint
            # then sum them together:
            total += datapoint.get(stat, 1)
        return total

    def get_metric_statistics(
            self, metrics_namespace, metric_name, statistics, dimensions
    ):
        return self.cloudwatch_client.get_metric_statistics(
            Namespace=metrics_namespace,
            MetricName=metric_name,
            StartTime=self.resolve_dt_time_format(self.start_time),
            EndTime=self.resolve_dt_time_format(self.end_time),
            Period=SECONDS_IN_A_DAY,
            Statistics=statistics,
            Dimensions=dimensions,
        )

    def prepare_metric_data(
            self, metric_tag, metric_name, response, sum_all_datapoints=True
    ):
        data = self.data_init()
        datapoints = response.get("Datapoints", [])
        # Add datapoints to the reporting payload:
        if datapoints:
            # Add the sum to the reporting payload:
            metric_tag = f"{metric_tag}-" if metric_tag else ""

            data["Data"][f"{metric_tag}{metric_name}"] = self.sum_datapoints(datapoints)
            if sum_all_datapoints:
                data["Data"]["datapoints"] = {
                    "SampleCount": self.sum_datapoints(datapoints, "SampleCount"),
                    "Average": self.sum_datapoints(datapoints, "Average"),
                    "Sum": self.sum_datapoints(datapoints, "Sum"),
                    "Minimum": self.sum_datapoints(datapoints, "Minimum"),
                    "Maximum": self.sum_datapoints(datapoints, "Maximum"),
                    "Unit": datapoints[0].get("Unit"),
                    "Timestamp": self.timestamp,
                }
        return data["Data"]

    def get_generic_metrics(self, metrics_to_sum, metric_tag=""):
        data = self.data_init()
        for metric_name in metrics_to_sum:
            # Sum all values for the metric over the past 24 hours:
            try:
                lambda_stat_response = self.get_metric_statistics(
                    metrics_namespace=METRICS_NAMESPACE,
                    metric_name=metric_name,
                    statistics=self.statistics,
                    dimensions=[{"Name": "stack-name", "Value": STACK_NAME}],
                )
                metric_data = self.prepare_metric_data(
                        response=lambda_stat_response,
                        metric_name=metric_name,
                        metric_tag=metric_tag,
                        sum_all_datapoints=False,
                    )
                if not metric_data:
                    raise ValueError(f"No metric data found for metric {metric_name}")

                data["Data"].update(metric_data)
            except Exception as e:
                logger.info(f"Fail to prepare metrics data for {metric_name}. Error: {e}")
                continue

        return data

    def get_cloudformation_metrics(self):
        metrics_to_sum = [
            "CloudFormation-CreateUpdate",
        ]
        return self.get_generic_metrics(metrics_to_sum)

    def get_lambda_metrics(self):
        metrics_to_sum = [
            "DeleteEfsFiles",
            "StartGlueJob",
        ]
        return self.get_generic_metrics(metrics_to_sum, "Lambda")

    def get_prebid_server_metrics(self):
        metrics_to_sum = [
            "AuctionRequests",
            "ImpsRequested",
        ]
        data = self.get_generic_metrics(metrics_to_sum, "PrebidServer")
        return data
    
    def get_prebid_cache_metrics(self):
        metrics_to_sum = [
            "GetNotFound",
            "GetSuccess",
            "PostFail",
            "PostCount",
            "PostSuccess"
        ]
        data = self.get_generic_metrics(metrics_to_sum, "PrebidCache")
        return data

    def get_cloudfront_metrics(self):
        # Cloudfront
        data = self.data_init()
        metric_tag = "CloudFront"
        namespace = f"AWS/{metric_tag}"
        cf_cw_response = self.cloudwatch_client.list_metrics(
            Namespace=namespace,
            Dimensions=[
                {"Name": "DistributionId", "Value": os.environ["CF_DISTRIBUTION_ID"]},
                {"Name": "Region", "Value": "Global"},
            ],
        )
        for cf_cw_metric in cf_cw_response.get("Metrics", []):
            cf_cw_metric_name = cf_cw_metric["MetricName"]
            try:
                cf_response = self.get_metric_statistics(
                    metrics_namespace=namespace,
                    metric_name=cf_cw_metric_name,
                    statistics=self.statistics,
                    dimensions=cf_cw_metric["Dimensions"],
                )

                metric_data = self.prepare_metric_data(
                    response=cf_response,
                    metric_name=cf_cw_metric_name,
                    metric_tag=metric_tag,
                )
                if not metric_data:
                    raise ValueError(f"No metric data found for metric {metric_tag}-{cf_cw_metric_name}")

                data["Data"].update(metric_data)

                metric = f"{metric_tag}-{cf_cw_metric_name}"
                data["MetricData"].setdefault(metric, {})
                data["MetricData"][metric].update(
                    {
                        "value": data["Data"][metric],
                        "dimensions": cf_cw_metric["Dimensions"],
                        "datapoints": data["Data"].pop("datapoints"),
                    }
                )
            except Exception as e:
                logger.info(f"Fail to prepare metrics data for {cf_cw_metric_name}. Error: {e}")
                continue

        return data

    def get_nat_gateway_ids(self, subnet_ids):
        nat_gateway_ids = []
        for subnet_id in subnet_ids:
            nat_gateway_response = self.ec2_client.describe_nat_gateways(
                Filters=[
                    {
                        "Name": "subnet-id",
                        "Values": [
                            subnet_id,
                        ],
                    },
                ]
            )
            nat_gateway_ids.extend([
                nat_gateway.get("NatGatewayId") for nat_gateway in nat_gateway_response.get("NatGateways", [])
                if nat_gateway.get("NatGatewayId")
            ])

        return nat_gateway_ids

    def get_nat_gateway_metrics(self):
        # NAT gateway
        metric_tag = "NATGateway"
        namespace = f"AWS/{metric_tag}"
        data = self.data_init()
        subnet_ids = json.loads(os.environ["SUBNET_IDS"])
        nat_gateway_ids = self.get_nat_gateway_ids(subnet_ids)
        for nat_gateway_id in nat_gateway_ids:
            nat_cw_response = self.cloudwatch_client.list_metrics(
                Namespace=namespace,
                Dimensions=[{"Name": "NatGatewayId", "Value": nat_gateway_id}],
            )
            for nat_metric in nat_cw_response.get("Metrics", []):
                nat_metric_name = nat_metric["MetricName"]
                try:
                    nat_cw_stat_response = self.get_metric_statistics(
                        metrics_namespace=namespace,
                        metric_name=nat_metric_name,
                        statistics=self.statistics,
                        dimensions=nat_metric["Dimensions"],
                    )
                    metric_data = self.prepare_metric_data(
                        response=nat_cw_stat_response,
                        metric_name=nat_metric_name,
                        metric_tag=metric_tag,
                    )
                    if not metric_data:
                        raise ValueError(f"No metric data found for metric {metric_tag}-{nat_metric_name}")

                    data["Data"].update(metric_data)

                    metric = f"{metric_tag}-{nat_metric_name}"
                    data["MetricData"].setdefault(metric, {})
                    data["MetricData"][metric].update(
                        {
                            "value": data["Data"][metric],
                            "dimensions": nat_metric["Dimensions"],
                            "datapoints": data["Data"].pop("datapoints"),
                        }
                    )
                except Exception as e:
                    logger.info(f"Fail to prepare metrics data for {nat_metric_name}. Error: {e}")
                    continue

        return data

    def get_application_elb_metrics(self):
        # Load Balancer
        metric_tag = "ApplicationELB"
        namespace = f"AWS/{metric_tag}"
        data = self.data_init()
        elb_response = self.cloudwatch_client.list_metrics(
            Namespace=namespace,
            Dimensions=[
                {"Name": "LoadBalancer", "Value": os.environ["LOAD_BALANCER_NAME"]}
            ],
        )
        for elb_metric in elb_response.get("Metrics", []):
            elb_metric_name = elb_metric["MetricName"]
            try:
                elb_stat_response = self.get_metric_statistics(
                    metrics_namespace=namespace,
                    metric_name=elb_metric_name,
                    statistics=["SampleCount", "Average", *self.statistics],
                    dimensions=elb_metric["Dimensions"],
                )
                metric_data = self.prepare_metric_data(
                    response=elb_stat_response,
                    metric_name=elb_metric_name,
                    metric_tag=metric_tag,
                )
                if not metric_data:
                    raise ValueError(f"No metric data found for metric {metric_tag}-{elb_metric_name}")

                data["Data"].update(metric_data)

                metric = f"{metric_tag}-{elb_metric_name}"
                data["MetricData"].setdefault(metric, {})
                data["MetricData"][metric].update(
                    {
                        "value": data["Data"][metric],
                        "dimensions": elb_metric["Dimensions"],
                        "datapoints": data["Data"].pop("datapoints"),
                    }
                )
            except Exception as e:
                logger.info(f"Fail to prepare metrics data for {elb_metric_name}. Error: {e}")
                continue

        return data
    
    def get_elasticache_metrics(self):
        metric_tag = "ElastiCache"
        namespace = f"AWS/{metric_tag}"
        data = self.data_init()
        elasticache_cluster_id = os.environ["ELASTICACHE_CLUSTER_ID"]
        elasticache_response = self.cloudwatch_client.list_metrics(
            Namespace=namespace,
            Dimensions=[
                {"Name": "clusterId", "Value": elasticache_cluster_id}
            ],
        )
        for elasticache_metric in elasticache_response.get("Metrics", []):
            elasticache_metric_name = elasticache_metric["MetricName"]
            try:
                elasticache_stat_response = self.get_metric_statistics(
                    metrics_namespace=namespace,
                    metric_name=elasticache_metric_name,
                    statistics=["SampleCount", "Average", *self.statistics],
                    dimensions=elasticache_metric["Dimensions"],
                )
                metric_data = self.prepare_metric_data(
                    response=elasticache_stat_response,
                    metric_name=elasticache_metric_name,
                    metric_tag=metric_tag,
                )
                if not metric_data:
                    raise ValueError(f"No metric data found for metric {metric_tag}-{elasticache_metric_name}")

                data["Data"].update(metric_data)

                metric = f"{metric_tag}-{elasticache_metric_name}"
                data["MetricData"].setdefault(metric, {})
                data["MetricData"][metric].update(
                    {
                        "value": data["Data"][metric],
                        "dimensions": elasticache_metric["Dimensions"],
                        "datapoints": data["Data"].pop("datapoints"),
                    }
                )
            except Exception as e:
                logger.info(f"Fail to prepare metrics data for {elasticache_metric_name}. Error: {e}")
                continue

        return data

    def get_uuid(self):
        return self.secrets_manager_client.get_secret_value(
            SecretId=f"{STACK_NAME}-anonymous-metrics-uuid"
        )["SecretString"]

    def get_metrics_report(self):
        data = {
            "Solution": SOLUTION_ID,
            "Version": SOLUTION_VERSION,
            "UUID": self.uuid,
            "Timestamp": self.resolve_dt_time_format(self.timestamp),
            "StartTime": self.resolve_dt_time_format(self.start_time),
            "EndTime": self.resolve_dt_time_format(self.end_time),
            **self.data_init(),
        }

        metric_funcs = [
            "get_lambda_metrics",
            "get_prebid_server_metrics",
            "get_cloudformation_metrics",
            "get_nat_gateway_metrics",
            "get_application_elb_metrics",
            "get_elasticache_metrics",
            "get_prebid_cache_metrics",
        ]

        if os.environ.get("CF_DISTRIBUTION_ID"):
            metric_funcs.append("get_cloudfront_metrics")

        for metric_func in metric_funcs:
            metric_report_data = getattr(self, metric_func)()
            if metric_func not in ["get_lambda_metrics", "get_prebid_server_metrics", "get_cloudformation_metrics"]:
                if metric_report_data["MetricData"]:
                    self.put_metric_data(metric_report_data["MetricData"])
            data["Data"].update(metric_report_data["Data"])

        data.pop("MetricData")
        return data

    def put_metric_data(self, metric_data):
        for metric_name, metric_data_value in metric_data.items():
            try:
                self.cloudwatch_client.put_metric_data(
                    Namespace=METRICS_NAMESPACE,
                    MetricData=[
                        {
                            "MetricName": metric_name,
                            "Dimensions": metric_data_value["dimensions"],
                            "Unit": metric_data_value["datapoints"]["Unit"],
                            "Timestamp": metric_data_value["datapoints"]["Timestamp"],
                            "StatisticValues": {
                                "SampleCount": metric_data_value["datapoints"][
                                    "SampleCount"
                                ],
                                "Sum": metric_data_value["datapoints"]["Sum"],
                                "Minimum": metric_data_value["datapoints"]["Minimum"],
                                "Maximum": metric_data_value["datapoints"]["Maximum"],
                            },
                        }
                    ],
                )
            except Exception as e:
                logger.info(f"Fail to put metric data on CloudWatch for {metric_name}. Error: {e}")
                continue


def event_handler(event, context):
    """
    This function is the entry point.
    """
    logger.info("We got the following event:\n")
    logger.info("event:\n {s}".format(s=event))
    logger.info("context:\n {s}".format(s=context))
    send_metrics()


def send_metrics():
    """
    This function is responsible for reporting cloudwatch metrics.
    """

    cloudwatch_metrics_report = CloudwatchMetricsReport()
    data = cloudwatch_metrics_report.get_metrics_report()

    # Send metric data:
    if SEND_ANONYMIZED_DATA == "Yes":
        if data["Data"]:
            logger.info("Reporting the following data:")
            logger.info(json.dumps(data))
            response = requests.post(METRICS_ENDPOINT, json=data, timeout=5)
            logger.info(f"Response status code = {response.status_code}")
        else:
            logger.info("No data to report.")
    else:
        logger.info("User opted out of anonymous metric reporting.")
