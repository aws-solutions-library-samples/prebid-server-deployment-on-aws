# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import sys
import json

import awsglue.transforms as awsglue_transforms
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql.functions import regexp_extract, sum, col
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrameCollection
from awsglue.dynamicframe import DynamicFrame
import concurrent.futures
import re
import boto3
from botocore import config
from datetime import datetime

args = getResolvedOptions(sys.argv, [
    "SOLUTION_ID",
    "SOLUTION_VERSION",
    "JOB_NAME",
    "SOURCE_BUCKET",
    "OUTPUT_BUCKET",
    "DATABASE_NAME",
    "ATHENA_QUERY_BUCKET",
    "AWS_REGION",
    "object_keys",
    "METRICS_NAMESPACE",
    "RESOURCE_PREFIX"
]
                          )

SOLUTION_ID = args["SOLUTION_ID"]
SOLUTION_VERSION = args["SOLUTION_VERSION"]
SOURCE_BUCKET = args["SOURCE_BUCKET"]
OUTPUT_BUCKET = args["OUTPUT_BUCKET"]
DATABASE_NAME = args["DATABASE_NAME"]
ATHENA_QUERY_BUCKET = args["ATHENA_QUERY_BUCKET"]
AWS_REGION = args["AWS_REGION"]
OBJECT_KEYS = json.loads(args["object_keys"])
METRICS_NAMESPACE = args["METRICS_NAMESPACE"]
RESOURCE_PREFIX = args["RESOURCE_PREFIX"]

append_solution_identifier = {
    "user_agent_extra": f"AwsSolution/{SOLUTION_ID}/{SOLUTION_VERSION}"
}
default_config = config.Config(**append_solution_identifier)


class GroupFilter:
    def __init__(self, name, filters):
        self.name = name
        self.filters = filters


def apply_group_filter(source_dyf, group):
    return awsglue_transforms.Filter.apply(frame=source_dyf, f=group.filters)


def threaded_route(glue_ctx, source_dyf, group_filters) -> DynamicFrameCollection:
    dynamic_frames = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_filter = {
            executor.submit(apply_group_filter, source_dyf, gf): gf
            for gf in group_filters
        }
        for future in concurrent.futures.as_completed(future_to_filter):
            gf = future_to_filter[future]
            if future.exception() is not None:
                print("%r generated an exception: %s" % (gf, future.exception()))
            else:
                dynamic_frames[gf.name] = future.result()
    return DynamicFrameCollection(dynamic_frames, glue_ctx)


def apply_regex_pattern(dataframe, column):
    return dataframe.withColumn(column, regexp_extract(dataframe["message"], f"{column}=([^,]+)", 1))


def create_metric_node(node, columns):
    dataframe = node.toDF()
    for col in columns:
        dataframe = apply_regex_pattern(dataframe, col)
    node = DynamicFrame.fromDF(dataframe, glueContext, "dynamic_frame")
    return node


def get_glue_schema(database_name, table_name):
    # Add the solution identifier to boto3 requests for attributing service API usage
    boto_config = {
        "user_agent_extra": f"AwsSolution/{SOLUTION_ID}/{SOLUTION_VERSION}"
    }
    client = boto3.client('glue', config=config.Config(**boto_config))
    response = client.get_table(
        DatabaseName=database_name,
        Name=table_name,
    )

    columns = response['Table']['StorageDescriptor']['Columns']
    partition_keys = response['Table']['PartitionKeys']
    schema = {}
    for col in columns + partition_keys:
        name = col['Name']
        data_type = col['Type']
        schema[name] = data_type
    return schema


def map_data_types(node, schema):
    transform_map = []
    for col_name, data_type in schema.items():
        transform_map.append((col_name, "String", col_name, data_type))

    node = node.apply_mapping(transform_map)
    return node


def repair_table(database_name, table_name, region):
    # Add the solution identifier to boto3 requests for attributing service API usage
    boto_config = {
        "region_name": region,
        "user_agent_extra": f"AwsSolution/{SOLUTION_ID}/{SOLUTION_VERSION}"
    }
    client = boto3.client("athena", config=config.Config(**boto_config))
    client.start_query_execution(
        QueryString=f"MSCK REPAIR TABLE `{database_name}`.`{table_name}`;",
        QueryExecutionContext={
            "Database": database_name
        },
        ResultConfiguration={
            "OutputLocation": f"s3://{ATHENA_QUERY_BUCKET}/athena_query_output/"
        }
    )


def send_metrics(metric_name, value):
    cloudwatch_client = boto3.client("cloudwatch", config=default_config)
    cloudwatch_client.put_metric_data(
        Namespace=METRICS_NAMESPACE,
        MetricData=[
            {
                'MetricName': metric_name,
                'Dimensions': [{'Name': 'stack-name', 'Value': RESOURCE_PREFIX}],
                'Value': value,
                'Unit': 'Count',
                "Timestamp": datetime.utcnow()
            }
        ]
    )


def get_prebid_server_metrics_sum(node: DynamicFrame, metrics_to_sum):
    result = node.toDF().filter(col("name").isin(metrics_to_sum)).agg(
        sum("count").alias("total_count"))
    total_count = result.collect()[0]["total_count"]
    return total_count if total_count else 0


def record_cloudwatch_metrics(node: DynamicFrame):
    auction_requests_metrics = ["app_requests", "debug_requests", "no_cookie_requests"]
    imps_requests_metrics = ["imps_requested"]

    auction_requests_count = get_prebid_server_metrics_sum(node, auction_requests_metrics)
    imps_count = get_prebid_server_metrics_sum(node, imps_requests_metrics)

    send_metrics("AuctionRequests", auction_requests_count)
    send_metrics("ImpsRequested", imps_count)


# Initialize Job Process
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

# Load source data from S3
df_node = glueContext.create_dynamic_frame.from_options(
    format_options={
        "multiline": False,
    },
    connection_type="s3",
    format="json",
    connection_options={
        "paths": [f"s3://{SOURCE_BUCKET}/{key}" for key in OBJECT_KEYS]
    }
)

# Drop unused fields
df_node = awsglue_transforms.DropFields.apply(
    frame=df_node,
    paths=["level", "logger", "thread"]
)

# convert to data frame
spark_df = df_node.toDF()

# Extract type value into new column
spark_df = spark_df.withColumn("type", regexp_extract(spark_df["message"], "type=([^,]+)", 1))

# Extract year_month into new column
spark_df = spark_df.withColumn("year_month", regexp_extract(spark_df["timestamp"], r"(\d{4}-\d{2})", 1))

# convert to dynamic frame
df_node = DynamicFrame.fromDF(spark_df, glueContext, "dynamic_frame")

# Rename containerId to container_id for consistent name patterns
df_node = df_node.rename_field("containerId", "container_id")

# Split dataframe by metric type
type_split_node = threaded_route(
    glueContext,
    source_dyf=df_node,
    group_filters=[
        GroupFilter(
            name="gauge", filters=lambda row: (bool(re.match("GAUGE", row["type"])))
        ),
        GroupFilter(
            name="histogram",
            filters=lambda row: (bool(re.match("HISTOGRAM", row["type"]))),
        ),
        GroupFilter(
            name="counter", filters=lambda row: (bool(re.match("COUNTER", row["type"])))
        ),
        GroupFilter(
            name="meter", filters=lambda row: (bool(re.match("METER", row["type"])))
        ),
        GroupFilter(
            name="timer", filters=lambda row: (bool(re.match("TIMER", row["type"])))
        )
    ],
)

# Map column data types and write to output bucket
metric_list = ["timer", "meter", "histogram", "counter", "gauge"]
for metric in metric_list:
    filtered_node = awsglue_transforms.SelectFromCollection.apply(
        dfc=type_split_node,
        key=metric
    )

    # Check if the node is empty or has no valid data
    if filtered_node.count() == 0 or filtered_node.toDF().schema == "root":
        print(f"Skipping metric type: {metric} because it has no data")
        continue

    schema = get_glue_schema(database_name=DATABASE_NAME, table_name=metric)
    cols = schema.keys()
    exclusion = ["year_month", "timestamp", "container_id"]
    cols = [item for item in cols if item not in exclusion]

    metric_node = create_metric_node(node=filtered_node, columns=cols)
    metric_node = awsglue_transforms.DropFields.apply(
        frame=metric_node,
        paths=["message"]
    )

    metric_node = map_data_types(node=metric_node, schema=schema)

    if metric == "counter":
        try:
            record_cloudwatch_metrics(metric_node)
        except Exception as e:
            print(f"Error recording cloudwatch metrics: {e}")

    glueContext.write_dynamic_frame.from_options(
        frame=metric_node,
        connection_type="s3",
        format="glueparquet",
        connection_options={
            "path": f"s3://{OUTPUT_BUCKET}/type={metric}",
            "partitionKeys": ["year_month"],
        },
        format_options={"compression": "gzip"}
    )

    repair_table(database_name=DATABASE_NAME, table_name=metric, region=AWS_REGION)

job.commit()
