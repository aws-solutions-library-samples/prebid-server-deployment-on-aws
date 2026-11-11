## Run functional tests 

### Prerequisite
* Deploy the solution before running the functional tests

### Usage:
```shell
cd source/tests/functional_tests

./run-functional-tests.sh [-h] [-v] [--in-venv] [--test-file-name] [--extras] [--region] --stack-name {STACK_NAME} --profile {PROFILE}
```

#### Required Parameter Details:
* `STACK_NAME`: name of the Cloudformation stack where the solution is running.
* `PROFILE`: the profile that you have setup in ~/.aws/credentials that you want to use for AWS CLI commands.

#### Optional Parameter Details:
* `--in-venv`: Run functional tests in an existing virtual environment. If not running the tests in a venv, leave this parameter. [--in-venv 1]
* `--test-file-name`: Run individual test file (optional) e.g --test-file-name test_bad_requests.py,
    Run individual test function (optional) e.g --test-file-name test_bad_requests py::test_request_rejected_by_waf_1
* `--region`: AWS region for CLI commands (optional, default to us-east-1)
* `--extras`: Append more commands to pytest run (optional)

#### The following options are available:
* `-h | --help`:       Print usage
* `-v | --verbose`:    Print script debug info

#### Test Histogram table
* The histogram test requires a load test of a deployed prebid-server stack with the AMT adapter enabled.
* To enable the AMT adapter, deploy the solution with the `deployBiddingSimulator` context flag:
  ```bash
  cdk deploy --all --context deployBiddingSimulator=true
  ```
* This automatically deploys the bidder simulator and configures the AMT adapter with the correct environment variables (`AMT_ADAPTER_ENABLED` and `AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT`).
* For other configuration instructions, see the [Load-Test README.MD](../../../source/loadtest/README.md).

#### RTB Fabric metrics test
* `test_rtb_fabric_metrics.py` validates that bid traffic flowed through the RTB Fabric link by querying the `AWS/RTBFabric` CloudWatch namespace (read-only). It asserts the link carried requests, a healthy success rate, `200 OK` responses, and published latency.
* Requires the stack deployed with RTB Fabric (the link id is read from the SSM param `/{stack-name}/fabric-link/link-id`, where the stack name comes from the runner's `PREBID_STACK_NAME` export) and prior traffic (the functional suite or a DLT run). On a non-RTB deployment the test cleanly skips.
* It runs as part of `run-functional-tests.sh`. Thresholds are env-configurable: `RTB_METRICS_LOOKBACK_HOURS` (default 6), `RTB_MIN_SUCCESS_RATE` (default 0.95), `RTB_MAX_AVG_LATENCY_MS` (default 60000).


