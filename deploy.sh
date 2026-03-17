#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Deployment script for Prebid Server on AWS
# This script handles AMT bidder file copying and CDK deployment

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
DEPLOY_BIDDING_SIMULATOR="false"
ENABLE_LOG_ANALYTICS="false"
INCLUDE_RTB_FABRIC="false"
AWS_PROFILE=""
AWS_REGION=""
CDK_COMMAND="deploy"
SKIP_COPY="false"

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to display usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Deployment script for Prebid Server on AWS. Handles AMT bidder file copying and CDK operations.

OPTIONS:
    --deploy-bidding-simulator    Deploy the bidding simulator stack (default: false)
    --enable-log-analytics        Enable log analytics (default: false)
    --include-rtb-fabric          Enable RTB Fabric integration (default: false)
    --profile PROFILE             AWS profile to use
    --region REGION               AWS region to deploy to
    --synth                       Run 'cdk synth' instead of 'cdk deploy'
    --skip-copy                   Skip AMT bidder file copying (for testing)
    -h, --help                    Display this help message

EXAMPLES:
    # Deploy with bidding simulator
    $0 --deploy-bidding-simulator --profile rtb --region us-east-1

    # Deploy with bidding simulator AND RTB Fabric integration
    $0 --deploy-bidding-simulator --include-rtb-fabric --profile rtb --region us-east-1

    # Deploy without bidding simulator
    $0 --profile rtb --region us-east-1

    # Deploy with analytics enabled
    $0 --enable-log-analytics --profile rtb --region us-east-1

    # Synthesize CloudFormation template
    $0 --synth --profile rtb --region us-east-1

EOF
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --deploy-bidding-simulator)
            DEPLOY_BIDDING_SIMULATOR="true"
            shift
            ;;
        --enable-log-analytics)
            ENABLE_LOG_ANALYTICS="true"
            shift
            ;;
        --include-rtb-fabric)
            INCLUDE_RTB_FABRIC="true"
            shift
            ;;
        --profile)
            AWS_PROFILE="$2"
            shift 2
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        --synth)
            CDK_COMMAND="synth"
            shift
            ;;
        --skip-copy)
            SKIP_COPY="true"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Get script directory and project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"

print_info "Project root: $PROJECT_ROOT"
print_info "Deploy bidding simulator: $DEPLOY_BIDDING_SIMULATOR"
print_info "Enable log analytics: $ENABLE_LOG_ANALYTICS"
print_info "Include RTB Fabric: $INCLUDE_RTB_FABRIC"

# Check if Docker daemon is running (required for CDK Docker builds)
print_info "Checking Docker daemon status..."
if ! docker info > /dev/null 2>&1; then
    print_error "Docker daemon is not running!"
    print_error "CDK deployment requires Docker for building container images."
    print_error "Please start Docker and try again."
    exit 1
fi
print_info "Docker daemon is running"

# Step 1: Copy AMT bidder files if deploying simulator
if [ "$DEPLOY_BIDDING_SIMULATOR" = "true" ] && [ "$SKIP_COPY" = "false" ]; then
    print_info "Copying AMT bidder files for Docker build..."
    
    SOURCE_DIR="$PROJECT_ROOT/source/loadtest/amt-bidder"
    DEST_DIR="$PROJECT_ROOT/deployment/ecr/prebid-server/amt-bidder"
    
    # Verify source directory exists
    if [ ! -d "$SOURCE_DIR" ]; then
        print_error "Source directory not found: $SOURCE_DIR"
        exit 1
    fi
    
    # Remove existing destination if it exists
    if [ -d "$DEST_DIR" ]; then
        print_warn "Removing existing AMT bidder directory at $DEST_DIR"
        rm -rf "$DEST_DIR"
    fi
    
    # Copy the directory
    print_info "Copying from $SOURCE_DIR to $DEST_DIR"
    cp -r "$SOURCE_DIR" "$DEST_DIR"
    
    # Ensure .gitkeep exists even after recreate
    touch "$DEST_DIR/.gitkeep"
    
    # Verify the copy
    if [ ! -d "$DEST_DIR" ]; then
        print_error "Failed to copy AMT bidder files"
        exit 1
    fi
    
    FILE_COUNT=$(find "$DEST_DIR" -type f | wc -l)
    print_info "Successfully copied AMT bidder files ($FILE_COUNT files)"
else
    if [ "$DEPLOY_BIDDING_SIMULATOR" = "false" ]; then
        print_info "Skipping AMT bidder file copy (simulator not being deployed)"
    else
        print_warn "Skipping AMT bidder file copy (--skip-copy flag set)"
    fi
fi

# Step 2: Set up Python virtual environment
print_info "Setting up Python virtual environment..."

cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
    print_info "Creating virtual environment..."
    python3 -m venv .venv
fi

print_info "Activating virtual environment..."
source .venv/bin/activate

# Step 3: Install dependencies
print_info "Installing Python dependencies..."
cd "$PROJECT_ROOT/source"

if [ ! -f "requirements-poetry.txt" ]; then
    print_error "requirements-poetry.txt not found in source directory"
    exit 1
fi

pip install -q -r requirements-poetry.txt
poetry install

# Step 4: Navigate to infrastructure directory
cd "$PROJECT_ROOT/source/infrastructure"

# Step 5: Build CDK command with context flags
CDK_ARGS=""

if [ -n "$AWS_PROFILE" ]; then
    CDK_ARGS="$CDK_ARGS --profile $AWS_PROFILE"
fi

if [ -n "$AWS_REGION" ]; then
    CDK_ARGS="$CDK_ARGS --region $AWS_REGION"
fi

if [ "$DEPLOY_BIDDING_SIMULATOR" = "true" ]; then
    CDK_ARGS="$CDK_ARGS --context deployBiddingSimulator=true"
fi

if [ "$ENABLE_LOG_ANALYTICS" = "true" ]; then
    CDK_ARGS="$CDK_ARGS --context enableLogAnalytics=true"
fi

if [ "$INCLUDE_RTB_FABRIC" = "true" ]; then
    CDK_ARGS="$CDK_ARGS --context includeRtbFabric=true"
fi

# Step 6: Run CDK command
if [ "$CDK_COMMAND" = "deploy" ]; then
    print_info "Running: cdk $CDK_COMMAND --all --require-approval never $CDK_ARGS"
    echo ""
    cdk $CDK_COMMAND --all --require-approval never $CDK_ARGS
else
    print_info "Running: cdk $CDK_COMMAND --all $CDK_ARGS"
    echo ""
    cdk $CDK_COMMAND --all $CDK_ARGS
fi

# Step 7: Cleanup message
echo ""
if [ "$CDK_COMMAND" = "deploy" ]; then
    print_info "Deployment complete!"
    
    if [ "$DEPLOY_BIDDING_SIMULATOR" = "true" ]; then
        print_info "Bidding simulator stack has been deployed"
        print_info "Check CloudFormation outputs for simulator endpoint URL"
    fi
    
    if [ "$ENABLE_LOG_ANALYTICS" = "true" ]; then
        print_info "Log analytics has been enabled"
    fi
    
    if [ "$INCLUDE_RTB_FABRIC" = "true" ]; then
        print_info "RTB Fabric integration has been enabled"
        print_info "Check CloudFormation outputs for RTB Fabric gateway endpoints"
    fi
else
    print_info "Synthesis complete!"
fi
print_info "Follow the readme for post deployment validation steps"