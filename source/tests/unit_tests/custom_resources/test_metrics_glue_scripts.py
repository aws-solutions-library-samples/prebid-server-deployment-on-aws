# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# ###############################################################################
# PURPOSE:
#   * Unit test for infrastructure/custom_resources/artifacts_bucket_lambda/files/metrics_glue_script.py.
# USAGE:
#   ./run-unit-tests.sh --test-file-name custom_resources/test_metrics_glue_scripts.py
###############################################################################

import sys
import os
import boto3
import json
import contextlib

import pytest
from moto import mock_aws
from unittest.mock import MagicMock, patch
from unit_tests.test_commons import FakeClass

DATABASE_NAME = "test-db"

mock_imports = [
    "awsglue",
    "awsglue.transforms",
    "awsglue.utils",
    "awsglue.job",
    "awsglue.context",
    "pyspark.context",
    "pyspark.sql.functions",
    "awsglue.dynamicframe",
    "gs_regex_extract"
]

class FakeImportClass(FakeClass):
    def getResolvedOptions(self, _, **k):
        return {
            "SOLUTION_ID": "solution-id",
            "SOLUTION_VERSION": "solution-version",
            "JOB_NAME": "job-name",
            "SOURCE_BUCKET": "source-bucket",
            "OUTPUT_BUCKET": "output-bucket",
            "DATABASE_NAME": DATABASE_NAME,
            "ATHENA_QUERY_BUCKET": "athena-bucket",
            "AWS_REGION": "us-east-1",
            "METRICS_NAMESPACE": "solution-metrics-namespace",
            "RESOURCE_PREFIX": "stack-name",
            "object_keys": json.dumps({"obj_key": "obj-val"})
        }
    
@contextlib.contextmanager
def mock_glue_db():
    with mock_aws():
        glue_client = boto3.client("glue", region_name=os.environ["AWS_REGION"])
        glue_client.create_database(DatabaseInput={"Name": DATABASE_NAME})
        glue_tb_names = ["timer", "meter", "histogram", "counter", "gauge"]

        for glue_tb_name in glue_tb_names:
            glue_client.create_table(
                DatabaseName=DATABASE_NAME,
                TableInput={
                    "Name": glue_tb_name,
                    "StorageDescriptor": {
                        "Columns": [{
                            "Name": "some-column-name",
                            "Type": "some-type"
                        }]
                    },
                    "PartitionKeys":[{
                    "Name": "some-part-column-name",
                    "Type": "create_table"
                }]
                },
                
            )
        yield


@pytest.fixture(autouse=True)
def mocked_imports():
    for mock_import in mock_imports:
        if "awsglue.utils" == mock_import:
            sys.modules[mock_import] = FakeImportClass
        else:
            sys.modules[mock_import] = MagicMock()


@mock_glue_db()
def test_group_filter():
    
    from custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script import GroupFilter

    filter_mock = MagicMock()
    group_filter = GroupFilter(name="test", filters=filter_mock)
    assert group_filter.name == "test"
    assert group_filter.filters == filter_mock



@mock_glue_db()
def test_apply_group_filter():
    from custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script import GroupFilter, apply_group_filter

    mock_def = MagicMock()
    group_filter = GroupFilter(name="test", filters=mock_def)
    apply_group_filter(source_dyf=mock_def, group=group_filter)


def test_threaded_route():
    from custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script import threaded_route, GroupFilter

    mock_def = MagicMock()
    group_filter = GroupFilter(name="test", filters=mock_def)
    threaded_route(glue_ctx=mock_def, source_dyf=mock_def, group_filters=[group_filter])


def test_apply_regex_pattern():
    from custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script import apply_regex_pattern

    mock_def = MagicMock()
    apply_regex_pattern(dataframe=mock_def, column=mock_def)


def test_create_metric_node():
    from custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script import create_metric_node

    mock_def = MagicMock()
    create_metric_node(node=mock_def, columns=[mock_def])


def test_map_data_types():
    from custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script import map_data_types

    mock_def = MagicMock()
    map_data_types(node=mock_def, schema={"some-key": "some_value"})


@mock_glue_db()
def test_get_glue_schema():
    from custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script import get_glue_schema

    schema = get_glue_schema(database_name=DATABASE_NAME, table_name="histogram")
    assert schema == {'some-column-name': 'some-type', 'some-part-column-name': 'create_table'}


@patch("custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script.boto3.client")
def test_repair_table(mock_boto3_client):
    from custom_resources.artifacts_bucket_lambda.files.glue.metrics_glue_script import repair_table

    mock_athena_client = mock_boto3_client.return_value
    mock_athena_client.return_value = None

    repair_table(
        database_name=DATABASE_NAME,
        table_name="some_table",
        region="us-east-1"
    )

    mock_athena_client.start_query_execution.assert_called_once_with(
        QueryString=f"MSCK REPAIR TABLE `{DATABASE_NAME}`.`some_table`;",
        QueryExecutionContext={
            "Database": DATABASE_NAME
        },
        ResultConfiguration={
            "OutputLocation": "s3://athena-bucket/athena_query_output/"
        }
    )
