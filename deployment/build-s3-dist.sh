#!/bin/bash
#
# This assumes all of the OS-level configuration has been completed and git repo has already been cloned
#
# This script should be run from the repo's deployment directory
# cd deployment
# ./build-s3-dist.sh source-bucket-base-name solution-name version-code
#
# Paramenters:
#  - source-bucket-base-name: Name for the S3 bucket location where the template will source the Lambda
#    code from. The template will append '-[region_name]' to this bucket name.
#    For example: ./build-s3-dist.sh solutions v1.1.4
#    The template will then expect the source code to be located in the solutions-[region_name] bucket
#
#  - solution-name: name of the solution for consistency
#
#  - version-code: version of the package

# set -euo pipefail

# Check to see if input has been provided:
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
    echo "Please provide the base source bucket name, trademark approved solution name and version where the lambda code will eventually reside."
    echo "For example: ./build-s3-dist.sh solutions trademarked-solution-name v1.1.5"
    exit 1
fi

SOLUTION_ID="SO0248"

# Get reference for all important folders
template_dir="$PWD"
template_dist_dir="$template_dir/global-s3-assets"
build_dist_dir="$template_dir/regional-s3-assets"
source_dir="$template_dir/../source"
cdk_out="$template_dir/cdk.out"

echo "------------------------------------------------------------------------------"
echo "[Init] Clean old dist, node_modules and bower_components folders"
echo "------------------------------------------------------------------------------"
echo "rm -rf $template_dist_dir"
rm -rf $template_dist_dir
echo "mkdir -p $template_dist_dir"
mkdir -p $template_dist_dir
echo "rm -rf $build_dist_dir"
rm -rf $build_dist_dir
echo "mkdir -p $build_dist_dir"
mkdir -p $build_dist_dir
# remove old cdk.out folder before build
rm -rf $cdk_out

# echo "------------------------------------------------------------------------------"
# echo "[Packing] Templates"
# echo "------------------------------------------------------------------------------"
# echo "cp $template_dir/*.template $template_dist_dir/"
# cp $template_dir/*.template $template_dist_dir/
# echo "copy yaml templates and rename"
# cp $template_dir/*.yaml $template_dist_dir/
# cd $template_dist_dir
# # Rename all *.yaml to *.template
# for f in *.yaml; do
#     mv -- "$f" "${f%.yaml}.template"
# done

# cd ..
# echo "Updating code source bucket in template with $1"
# replace="s/%%SOLUTION_ID%%/$SOLUTION_ID/g"
# echo "sed -i '' -e $replace $template_dist_dir/*.template"
# sed -i '' -e $replace $template_dist_dir/*.template
# replace="s/%%BUCKET_NAME%%/$1/g"
# echo "sed -i '' -e $replace $template_dist_dir/*.template"
# sed -i '' -e $replace $template_dist_dir/*.template
# replace="s/%%BUCKET_NAME%%/$1/g"
# echo "sed -i '' -e $replace $template_dist_dir/*.template"
# sed -i '' -e $replace $template_dist_dir/*.template
# replace="s/%%SOLUTION_NAME%%/$2/g"
# echo "sed -i '' -e $replace $template_dist_dir/*.template"
# sed -i '' -e $replace $template_dist_dir/*.template
# replace="s/%%VERSION%%/$3/g"
# echo "sed -i '' -e $replace $template_dist_dir/*.template"
# sed -i '' -e $replace $template_dist_dir/*.template

echo "------------------------------------------------------------------------------"
echo "[Rebuild] CDK Solution"
echo "------------------------------------------------------------------------------"

# do we need a virtual environment, or are we using one now?
build_venv_name=".venv_build"
build_venv_dir="$template_dir/$build_venv_name"

# clean up testing venv if present
rm -rf $build_venv_dir

# check if we need a new testing venv
./venv_check.py
if [ "$?" == "1" ]; then
    echo 'creating temporary virtual environment for build'
    python3 -m venv $build_venv_name
    source $build_venv_name/bin/activate
    # configure the environment
    pip install --upgrade pip
    pip install --upgrade -r $source_dir/requirements.txt
else
    echo 'using currently activated virtual environment for build'
    echo 'deactivate your virtual environment to use a script-generated one'
fi

# generate the templates (unbundled)
cd $source_dir/
cdk synth -o $cdk_out

# If this is a release pipeline and the ecr_image_tags.json file references a
# version that is different from the $VERSION environment variable then
# exit with an error to stop the pipeline. This is intended to help prevent
# accidentally overwriting a prebid-server image that has already been
# published to the aws-solutions public repo. This can happen if a developer
# has forgotten to update ecr_image_tags.json and it still refers to a
# previously published version.
if [ "${PIPELINE_TYPE:-}" = "release" ]; then
  # The ${PIPELINE_TYPE:-} syntax provides a safe way to reference potentially
  # undefined variables, defaulting to an empty string if the variable isn't
  # set.
  echo "This is a Release pipeline"
  echo "------------------------------------------------------------------------------"
  echo "[Validation] Check docker image tag prior to publishing to Amazon ECR"
  echo "------------------------------------------------------------------------------"
  TAGS_JSON_FILE="$template_dir/ecr_image_tags.json"
  TAGS_JSON_FILE_EXISTS=$( [ -e $TAGS_JSON_FILE ] && echo true || echo false )
  if [ TAGS_JSON_FILE_EXISTS ]; then
      echo "Checking if version in ecr_image_tags.json matches $VERSION"
      CUSTOM_TAG=$(jq -r --arg key "$IMAGE" '.[$key]' $TAGS_JSON_FILE)
      if [ "$CUSTOM_TAG" != "$VERSION" ]; then
          echo "ecr_image_tags.json version does not match $VERSION"
          exit 1
      fi
  fi
fi
