#!/bin/bash
###############################################################################
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
###############################################################################

set -exuo pipefail

usage() {
  msg "$msg"
  cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [-h] [-v] [--in-venv] [--test-file-name] [--extras] [--region] --profile PROFILE --stack-name STACK_NAME

Available options:

-h, --help        Print this help and exit (optional)
-v, --verbose     Print script debug info (optional)
--in-venv         Run test in an existing virtual environment [--in-venv 1] (optional)
--extras          Append more commands to pytest run (optional)
--stack-name      Name of the Cloudformation stack where the solution is running
--profile         AWS profile for CLI commands
--region          AWS region for CLI commands (optional, default to us-east-1)
--test-file-name  Run individual test file (optional) e.g --test-file-name test_bad_requests.py,
                  Run individual test function (optional) e.g --test-file-name test_bad_requests.py::test_request_rejected_by_waf_1

EOF
  exit 1
}

msg() {
  echo >&2 -e "${1-}"
}

parse_params() {
  # default values of variables set from params
  flag=0
  param=''

  while :; do
    case "${1-}" in
    -h | --help) usage ;;
    -v | --verbose) set -x ;;
    --in-venv)
      in_venv="${2}"
      shift
      ;;
    --extras)
      extras="${2}"
      shift
      ;;
    --stack-name)
      stack_name="${2}"
      shift
      ;;
    --profile)
      profile="${2}"
      shift
      ;;
    --region)
      region="${2}"
      shift
      ;;
    --test-file-name)
      TEST_FILE_NAME="${2}" ;;
    *) break ;;
    esac
    shift
  done

  args=("$@")

  # check required params and arguments
  [[ -z "${profile}" ]] && usage "Missing required parameter: profile"
  [[ -z "${stack-name}" ]] && usage "Missing required parameter: stack-name"

  return 0
}

parse_params "$@"

default_region=${region:-"us-east-1"}

msg "Parameters:"
msg "- Stack name: ${stack_name}"
msg "- Profile: ${profile}"
msg "- Region: ${default_region}"

# Get reference for all important folders
current_dir="$PWD"
source_dir="$(
  cd $current_dir/../../../source
  pwd -P
)"

echo "------------------------------------------------------------------------------"
echo "Creating a temporary Python virtualenv for this script"
echo "------------------------------------------------------------------------------"
# Make sure aws cli is installed
if [[ ! -x "$(command -v aws)" ]]; then
  echo "ERROR: This script requires the AWS CLI to be installed. Please install it then run again."
  exit 1
fi

create_venv() {
  if [[ ${in_venv:-0} -ne 1 ]]; then
    echo "Create virtual python environment:"
    VENV=$(mktemp -d) && echo "$VENV"
    command -v python3 >/dev/null
    if [ $? -ne 0 ]; then
      echo "ERROR: install Python3 before running this script"
      exit 1
    fi
    python3 -m venv "$VENV"
    source "$VENV"/bin/activate
    pip3 install wheel
    pip3 install --quiet -r requirements-test.txt
  else
    echo "Run tests in a virtualenv, skip creating virtualenv"
  fi
}

create_venv


#################################
####   TEST Prebid Server   #####
#################################
echo "Test Prebid Server"

cd $current_dir

export CLOUDFRONT_ENDPOINT=$(aws cloudformation describe-stacks --stack-name $stack_name --query "Stacks[].Outputs[?OutputKey=='PrebidCloudFrontDistributionEndpoint'].OutputValue" --output text --profile $profile --region $default_region)

export GLUE_JOB_NAME=$(aws cloudformation list-stack-resources \
    --stack-name $stack_name \
    --query 'StackResourceSummaries[?starts_with(LogicalResourceId, `MetricsEtlJob`) && ResourceType==`AWS::Glue::Job` && (ResourceStatus==`CREATE_COMPLETE` || ResourceStatus==`UPDATE_COMPLETE`)].PhysicalResourceId' \
    --profile $profile --region $default_region \
    --output text)

export ATHENA_DATABASE=$(aws cloudformation list-stack-resources \
    --stack-name $stack_name \
    --query 'StackResourceSummaries[?starts_with(LogicalResourceId, `MetricsEtlDatabase`) && ResourceType==`AWS::Glue::Database` && (ResourceStatus==`CREATE_COMPLETE` || ResourceStatus==`UPDATE_COMPLETE`)].PhysicalResourceId' \
    --profile $profile --region $default_region \
    --output text)

export ATHENA_QUERY_OUTPUT=$(aws cloudformation list-stack-resources \
    --stack-name $stack_name \
    --query 'StackResourceSummaries[?starts_with(LogicalResourceId, `ArtifactsBucket`) && ResourceType==`AWS::S3::Bucket` && (ResourceStatus==`CREATE_COMPLETE` || ResourceStatus==`UPDATE_COMPLETE`)].PhysicalResourceId' \
    --profile $profile --region $default_region \
    --output text)

export ANALYTICS_BUCKET=$(aws cloudformation list-stack-resources \
    --stack-name $stack_name \
    --query 'StackResourceSummaries[?starts_with(LogicalResourceId, `MetricsEtlDataSyncAnalyticsBucket`) && ResourceType==`AWS::S3::Bucket` && (ResourceStatus==`CREATE_COMPLETE` || ResourceStatus==`UPDATE_COMPLETE`)].PhysicalResourceId' \
    --profile $profile --region $default_region \
    --output text)

export METRICS_BUCKET=$(aws cloudformation list-stack-resources \
    --stack-name $stack_name \
    --query 'StackResourceSummaries[?starts_with(LogicalResourceId, `MetricsEtlDataSyncMetricsBucket`) && ResourceType==`AWS::S3::Bucket` && (ResourceStatus==`CREATE_COMPLETE` || ResourceStatus==`UPDATE_COMPLETE`)].PhysicalResourceId' \
    --profile $profile --region $default_region \
    --output text)

# This will be used to test histogram metrics if load test is setup for the stack
TASK_DEF_FAMILY=$(aws cloudformation list-stack-resources \
    --stack-name $stack_name \
    --query 'StackResourceSummaries[?starts_with(LogicalResourceId, `CloudFrontEntryDeploymentECSTaskPrebidTaskDef`) && ResourceType==`AWS::ECS::TaskDefinition` && (ResourceStatus==`CREATE_COMPLETE` || ResourceStatus==`UPDATE_COMPLETE`)].PhysicalResourceId' \
    --profile $profile --region $default_region \
    --output text | awk -F'/' '{print $NF}' | cut -d':' -f1)

# Get latest task definition ARN, updated by NW post deploy script.
LATEST_TASK_DEF=$(aws ecs list-task-definitions \
    --family-prefix $TASK_DEF_FAMILY \
    --sort DESC \
    --max-items 1 \
    --profile $profile --region $default_region \
    --output json | jq -r '.taskDefinitionArns[0]')

echo "Using latest task definition: $LATEST_TASK_DEF"

# export any environment variable found for the container
# AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT and AMT_ADAPTER_ENABLED are required test histogram data
eval $(aws ecs describe-task-definition \
    --task-definition $LATEST_TASK_DEF \
    --query 'taskDefinition.containerDefinitions[?name==`Prebid-Container`].environment[]' \
    --profile $profile --region $default_region \
    --output text | while read name value; do
        echo "export ${name}=${value}"
    done)
  
export TEST_AWS_REGION=$default_region
export TEST_AWS_PROFILE=$profile

TEST_FILE_NAME=./${TEST_FILE_NAME-}

# Common test options
TEST_OPTIONS="-vv -s -W ignore::DeprecationWarning -p no:cacheproviders ${extras-}"

# Check if poetry exists in POETRY_HOME
if [ -n "${POETRY_HOME:-}" ] && [ -f "$POETRY_HOME/bin/poetry" ]; then
    echo "Found poetry at: $POETRY_HOME/bin/poetry"
    if [ ! -L "/usr/local/bin/poetry" ]; then
      ln -s "$POETRY_HOME/bin/poetry" /usr/local/bin/poetry
    fi
    poetry run pytest $TEST_FILE_NAME $TEST_OPTIONS

# Check if poetry exists in system PATH
elif command -v poetry &> /dev/null; then
    echo "Found poetry in system PATH"
    poetry run pytest $TEST_FILE_NAME $TEST_OPTIONS

# Fallback to system pytest
else
    echo "Using system pytest as poetry was not found"
    pytest $TEST_FILE_NAME $TEST_OPTIONS
fi

if [[ ${in_venv:-0} -ne 1 ]]; then
  echo "Deactivate virtualenv"
  deactivate
else
  echo "Run tests in virtualenv, no deactivate"
fi

echo "End of all tests"
exit 0