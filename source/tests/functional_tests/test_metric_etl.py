#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0


#!/usr/bin/env python3

"""
Integration tests for ETL metrics processing using AWS Glue and Athena.
Tests verify the ETL pipeline by monitoring Glue jobs and querying Athena tables.
"""

import os
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional
import pytest
from conftest import SKIP_REASON, TEST_REGIONS, logging


logger = logging.getLogger(__name__)

# Constants
DEFAULT_TIMEOUT = 7200  # 2 hours
POLLING_INTERVAL = 300  # 5 minutes
MAX_ATHENA_RETRIES = 60

@dataclass
class ETLConfig:
    """Configuration for ETL testing environment"""
    database: str
    query_output: str
    glue_job_name: str
    timeout: int = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> 'ETLConfig':
        """Create configuration from environment variables"""
        required_vars = {
            'ATHENA_DATABASE': 'Athena Database name',
            'ATHENA_QUERY_OUTPUT': 'Athena Query Output Location (S3)',
            'GLUE_JOB_NAME': 'Glue Job Name'
        }

        # Validate required environment variables
        for var, description in required_vars.items():
            if var not in os.environ:
                raise ValueError(f"Required environment variable {var} not set - {description}")

        return cls(
            database=os.environ['ATHENA_DATABASE'],
            query_output=os.environ['ATHENA_QUERY_OUTPUT'],
            glue_job_name=os.environ['GLUE_JOB_NAME'],
            timeout=int(os.environ.get('TIMEOUT', DEFAULT_TIMEOUT))
        )

class GlueJobMonitor:
    """Handles Glue job monitoring and status checking"""
    
    def __init__(self, glue_client, job_name: str, timeout: int):
        self.client = glue_client
        self.job_name = job_name
        self.timeout = timeout

    def get_latest_run(self) -> Optional[str]:
        """Get the latest job run ID"""
        response = self.client.get_job_runs(JobName=self.job_name)
        if not response["JobRuns"]:
            logger.info("No Glue job runs found.")
            return None
        
        latest_run = response["JobRuns"][0]
        run_id = latest_run["Id"]
        logger.info(f"Latest Glue job run ID: {run_id}")
        return run_id

    def monitor_job(self, run_id: str) -> str:
        """Monitor job until completion or timeout"""
        start_time = time.time()
        while True:
            if time.time() - start_time > self.timeout:
                logger.error("Glue job run timed out.")
                return "TIMEOUT"

            response = self.client.get_job_run(
                JobName=self.job_name,
                RunId=run_id
            )
            status = response["JobRun"]["JobRunState"]
            logger.info(f"Glue job run status: {status}")
            
            if status in ["SUCCEEDED", "FAILED"]:
                return status
            time.sleep(10)

class AthenaQueryExecutor:
    """Handles Athena query execution and results retrieval"""

    def __init__(self, athena_client, config: ETLConfig):
        self.client = athena_client
        self.config = config

    def query_table(self, table_name: str) -> Dict:
        """Execute query on specified table and return results"""
        query = f"SELECT * FROM {table_name} LIMIT 1"
        
        # Start query execution
        response = self.client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": self.config.database},
            ResultConfiguration={
                "OutputLocation": f"s3://{self.config.query_output}/functional_test"
            }
        )
        query_id = response["QueryExecutionId"]

        retry_count = 0
        # Wait for query completion
        while True:
            result = self.client.get_query_execution(QueryExecutionId=query_id)
            status = result["QueryExecution"]["Status"]["State"]
            logger.info(f"Athena query status: {status}")
            
            if status in ["SUCCEEDED", "FAILED"]:
                if status == "SUCCEEDED":
                    return self._get_query_results(query_id)
                raise Exception(f"Athena query failed: {status}")
            elif retry_count > MAX_ATHENA_RETRIES:
                raise AssertionError(f"{query} - Athena has elasped MAX_ATHENA_RETRIES {retry_count}: {status}")
            retry_count += 1
            time.sleep(10)

    def _get_query_results(self, query_id: str) -> Optional[Dict]:
        """Retrieve query results"""
        result = self.client.get_query_results(QueryExecutionId=query_id)
        records = result.get("ResultSet", {}).get("Rows", [])
        
        if len(records) > 1:
            logger.info(f"Record returned from Athena: {records[1]}")
            return records[1]
        return None

# Fixtures
@pytest.fixture(scope="session")
def config() -> ETLConfig:
    """Provide test configuration"""
    return ETLConfig.from_env()

@pytest.fixture(scope="session")
def get_service_session() -> Callable:
    """Create AWS service clients"""
    def _create_client(service_name: str):
        import boto3
        session = boto3.Session(
            region_name=os.environ["TEST_AWS_REGION"],
            profile_name=os.environ["TEST_AWS_PROFILE"]
        )
        return session.client(service_name)
    return _create_client

@pytest.fixture(scope="function")
def glue_monitor(get_service_session, config) -> GlueJobMonitor:
    """Provide Glue job monitor"""
    glue_client = get_service_session("glue")
    return GlueJobMonitor(glue_client, config.glue_job_name, config.timeout)

@pytest.fixture(scope="function")
def athena_executor(get_service_session, config) -> AthenaQueryExecutor:
    """Provide Athena query executor"""
    athena_client = get_service_session("athena")
    return AthenaQueryExecutor(athena_client, config)

@pytest.fixture(scope="function")
def get_athena_executor_results() -> Callable:
    """ Get Athena query results """
    def _get_executor_results(athena_executor: AthenaQueryExecutor, table_name: str) -> str:
        logger.info(f"Athena {table_name} table query results...")
        time.sleep(10)
        retry_count = 0
        result = athena_executor.query_table(table_name)
        while result is None:
            logger.info(f"Waiting for Athena {table_name} table query results...")
            time.sleep(10)
            result = athena_executor.query_table(table_name)
            if retry_count > MAX_ATHENA_RETRIES:
                raise AssertionError(f"{table_name} metrics not found in Athena.")
            retry_count += 1
        return result
    return _get_executor_results

# Test configurations for different metric types
METRIC_TABLES = {
    'counter': {'table': 'counter', 'depends': ['test_glue_job']},
    'gauge': {'table': 'gauge', 'depends': ['test_counter']},
    'meter': {'table': 'meter', 'depends': ['test_counter']},
    'timer': {'table': 'timer', 'depends': ['test_counter']},
    'histogram': {
        'table': 'histogram',
        'depends': ['test_counter', 'test_gauge', 'test_meter', 'test_timer']
    }
}

# Tests
@pytest.mark.skipif(
    os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
    reason=SKIP_REASON
)
@pytest.mark.order(after="test_prebid_auction.py::test_auction_request")
def test_glue_job(glue_monitor):
    """Test Glue ETL job execution"""
    start_time = time.time()
    while True:
        if time.time() - start_time > DEFAULT_TIMEOUT:
            raise AssertionError("Timed out waiting for Glue job.")

        run_id = glue_monitor.get_latest_run()
        if run_id:
            status = glue_monitor.monitor_job(run_id)
            if status == "SUCCEEDED":
                break
            elif status == "FAILED":
                raise AssertionError("Glue job failed.")

        logger.info(f"Waiting {POLLING_INTERVAL // 60} minutes for job run...")
        time.sleep(POLLING_INTERVAL)

def generate_metric_test(name: str, config: Dict):
    """Generate test function for specific metric type"""
    @pytest.mark.skipif(
        os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
        reason=SKIP_REASON
    )
    @pytest.mark.order(after=config['depends'])
    def test_func(athena_executor, get_athena_executor_results):
       result = get_athena_executor_results(athena_executor, config['table'])
       assert result is not None
    
    test_func.__name__ = f'test_{name}'
    return test_func

# Generate test functions for each metric type
for metric_name, metric_config in METRIC_TABLES.items():
    if metric_name != 'histogram':
        globals()[f'test_{metric_name}'] = generate_metric_test(metric_name, metric_config)

# Special case for histogram test due to additional conditions
@pytest.mark.skipif(
    not (os.environ.get("AMT_ADAPTER_ENABLED") and 
    os.environ.get("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT")),
    reason="Histogram test runs with amt adapter enabled."
)
@pytest.mark.skipif(
    os.environ["TEST_AWS_REGION"] not in TEST_REGIONS,
    reason=SKIP_REASON
)
@pytest.mark.order(after=METRIC_TABLES['histogram']['depends'])
def test_histogram(athena_executor, get_athena_executor_results):
    """Test histogram metrics"""
    result = get_athena_executor_results(athena_executor, METRIC_TABLES['histogram']['table'])
    assert result is not None
