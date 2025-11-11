#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# This assumes all of the OS-level configuration has been completed and git repo has already been cloned
#
# This script should be run from the repo's deployment directory
# cd deployment
# ./run-unit-tests.sh
#

[ "$DEBUG" == 'true' ] && set -x
# set -e

usage() {
  msg "$msg"
  cat <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [-h] [-v] [--in-venv] [--test-file-name] [--extras]

Available options:

-h, --help        Print this help and exit (optional)
--in-venv         Run test in an existing virtual environment [--in-venv 1] (optional)
--extras          Append more commands to pytest run (optional)
--test-file-name  Run individual test file (optional) e.g --test-file-name prebid_server/test_prebid_artifacts_constructs.py

EOF
  exit 1
}

# Get reference for all important folders
template_dir="$PWD"
source_dir="$(
  cd $template_dir/../source
  pwd -P
)"
root_dir="$template_dir/.."
venv_folder=".venv-temp"
tests_folder="$source_dir/tests/unit_tests"

while :; do
  case "${1-}" in
  -h | --help) usage ;;
  --in-venv)
    in_venv="${2}"
    shift
    ;;
  --test-file-name)
    TEST_FILE_NAME="${2}"
    shift
    ;;
  --extras)
    extras="${2}"
    ;;
  *) break ;;
  esac
  shift
done

# check if we need a new testing venv, or use active (workstation testing)
python3 ./venv_check.py
if [[ ${in_venv:-0} -ne 1 ]]; then
  echo "------------------------------------------------------------------------------"
  echo "[Env] Create clean virtual environment and install dependencies"
  echo "------------------------------------------------------------------------------"
  cd $root_dir

  if [ -d $venv_folder ]; then
      rm -rf $venv_folder
  fi
  python3 -m venv $venv_folder
  source $venv_folder/bin/activate

  # Check if poetry is installed
  if ! command -v poetry &> /dev/null && [ ! -f "$POETRY_HOME/bin/poetry" ]; then
    echo "Installing poetry..."
    pip install --upgrade pip
    cd $source_dir && pip install -q -r requirements-poetry.txt
  elif [ -f "$POETRY_HOME/bin/poetry" ]; then
    # Create symlink if poetry exists in POETRY_HOME
    ln -s "$POETRY_HOME/bin/poetry" /usr/local/bin/poetry
  fi

  cd $source_dir

  # Check if poetry.lock needs to be updated
  if poetry check 2>&1 | grep -q "poetry.lock was last generated"; then
      echo "------------------------------------------------------------------------------"
      echo "[Poetry] Lock file needs to be updated"
      echo "------------------------------------------------------------------------------"
      poetry lock
  fi

  echo "Install dependencies using poetry"
  poetry install --no-root

else
  echo "------------------------------------------------------------------------------"
  echo "[Env] Using active virtual environment for tests"
  echo "------------------------------------------------------------------------------"
  echo ''
fi

echo "------------------------------------------------------------------------------"
echo "[Test] Run pytest with coverage"
echo "------------------------------------------------------------------------------"
cd $source_dir
# setup coverage report path
coverage_report_path=$tests_folder/coverage-reports/source.coverage.xml
echo "coverage report path set to $coverage_report_path"
# disable __pycache__ files to prevent being packaged with lambda code
export PYTHONDONTWRITEBYTECODE=1
# run unit tests
TEST_FILE_NAME=$tests_folder/$TEST_FILE_NAME
poetry run pytest $TEST_FILE_NAME ${extras-} --cov=$source_dir/infrastructure/ --cov-report term-missing --cov-report term --cov-report "xml:$coverage_report_path" --cov-config=$source_dir/.coveragerc -vv

# The pytest --cov with its parameters and .coveragerc generates a xml cov-report with `coverage/sources` list
# with absolute path for the source directories. To avoid dependencies of tools (such as SonarQube) on different
# absolute paths for source directories, this substitution is used to convert each absolute source directory
# path to the corresponding project relative path. The $source_dir holds the absolute path for source directory.
sed -i -e "s,<source>$source_dir,<source>source,g" $coverage_report_path

if [[ ${in_venv:-0} -ne 1 ]]; then
  echo "------------------------------------------------------------------------------"
  echo "[Env] Deactivating test virtual environment"
  echo "------------------------------------------------------------------------------"
  echo ''

  if [ -d $venv_folder ]; then
      # deactivate the virtual environment
    deactivate
  fi
else
  echo "------------------------------------------------------------------------------"
  echo "[Env] Leaving virtual environment active"
  echo "------------------------------------------------------------------------------"
  echo ''

fi

cd $template_dirs

exit 0
