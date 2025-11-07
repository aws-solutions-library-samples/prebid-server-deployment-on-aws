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
* Follow instructions in [Load-Test README.MD](../../../source/loadtest/README.md)
* Histogram test requires a load test of a deployed prebid-server stack with `AMT_ADAPTER_ENABLED` and `AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT` running.


