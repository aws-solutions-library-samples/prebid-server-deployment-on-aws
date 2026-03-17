#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Destruction script for Prebid Server on AWS
# This script handles proper teardown of all CDK stacks in the correct order

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
AWS_PROFILE=""
AWS_REGION=""
FORCE="false"
DRY_RUN="false"

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

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Function to display usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Destruction script for Prebid Server on AWS. Destroys all CDK stacks in the correct order.

IMPORTANT: This will permanently delete all resources including:
  - Prebid Server infrastructure
  - Bidding simulator (if deployed)
  - RTB Fabric resources (if deployed)
  - S3 buckets and their contents
  - CloudWatch logs
  - All associated data

OPTIONS:
    --profile PROFILE    AWS profile to use (optional, uses default if not specified)
    --region REGION      AWS region where stacks are deployed (optional, uses default if not specified)
    --force              Skip confirmation prompts (use with caution!)
    --dry-run            Show what would be destroyed without actually destroying
    -h, --help           Display this help message

EXAMPLES:
    # Destroy with confirmation prompts (using default profile and region)
    $0

    # Destroy with specific profile and region
    $0 --profile rtb --region us-east-1

    # Destroy without confirmation (dangerous!)
    $0 --profile rtb --region us-east-1 --force

    # Preview what would be destroyed
    $0 --profile rtb --region us-east-1 --dry-run

DESTRUCTION ORDER:
    1. Detect deployed stacks
    2. Destroy PrebidServerStack (main infrastructure)
    3. Destroy BidderSimulatorStack (if exists)
    
    Note: RTB Fabric resources (Fabric Link, Requester Gateway, Responder Gateway)
    are automatically destroyed as part of their parent stacks due to CloudFormation
    dependency management.

EOF
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)
            AWS_PROFILE="$2"
            shift 2
            ;;
        --region)
            AWS_REGION="$2"
            shift 2
            ;;
        --force)
            FORCE="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
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

if [ -n "$AWS_PROFILE" ]; then
    print_info "AWS Profile: $AWS_PROFILE"
else
    print_info "AWS Profile: (using default)"
fi

if [ -n "$AWS_REGION" ]; then
    print_info "AWS Region: $AWS_REGION"
else
    print_info "AWS Region: (using default)"
fi

if [ "$DRY_RUN" = "true" ]; then
    print_warn "DRY RUN MODE - No resources will be destroyed"
fi

# Step 1: Build AWS CLI arguments
AWS_ARGS=()
if [ -n "$AWS_PROFILE" ]; then
    AWS_ARGS+=(--profile "$AWS_PROFILE")
fi
if [ -n "$AWS_REGION" ]; then
    AWS_ARGS+=(--region "$AWS_REGION")
fi

# Step 2: Detect deployed stacks
print_step "Detecting deployed stacks..."

PREBID_STACK_NAME="prebid-server-deployment-on-aws"
SIMULATOR_STACK_NAME="BiddingServerSimulator"

# Check if PrebidServerStack exists
PREBID_STACK_EXISTS="false"
if aws cloudformation describe-stacks --stack-name "$PREBID_STACK_NAME" "${AWS_ARGS[@]}" > /dev/null 2>&1; then
    PREBID_STACK_EXISTS="true"
    print_info "Found: $PREBID_STACK_NAME"
else
    print_warn "Not found: $PREBID_STACK_NAME"
fi

# Check if BidderSimulatorStack exists
SIMULATOR_STACK_EXISTS="false"
if aws cloudformation describe-stacks --stack-name "$SIMULATOR_STACK_NAME" "${AWS_ARGS[@]}" > /dev/null 2>&1; then
    SIMULATOR_STACK_EXISTS="true"
    print_info "Found: $SIMULATOR_STACK_NAME"
else
    print_warn "Not found: $SIMULATOR_STACK_NAME"
fi

# Check if any stacks exist
if [ "$PREBID_STACK_EXISTS" = "false" ] && [ "$SIMULATOR_STACK_EXISTS" = "false" ]; then
    print_warn "No stacks found to destroy"
    exit 0
fi

# Step 3: Display destruction plan
echo ""
print_step "Destruction Plan:"
echo ""

if [ "$PREBID_STACK_EXISTS" = "true" ]; then
    echo "  1. Destroy $PREBID_STACK_NAME"
    echo "     - Prebid Server ECS tasks and services"
    echo "     - Application Load Balancer"
    echo "     - CloudFront distribution (if deployed)"
    echo "     - WAF WebACL (if deployed)"
    echo "     - VPC and networking resources"
    echo "     - EFS file system"
    echo "     - S3 buckets (stored requests, artifacts, logs)"
    echo "     - CloudWatch logs and metrics"
    echo "     - Glue ETL jobs"
    echo "     - Lambda functions"
    echo "     - RTB Fabric Requester Gateway (if deployed)"
    echo "     - RTB Fabric Link (if deployed)"
    echo ""
fi

if [ "$SIMULATOR_STACK_EXISTS" = "true" ]; then
    echo "  2. Destroy $SIMULATOR_STACK_NAME"
    echo "     - Bidder simulator Lambda functions"
    echo "     - Application Load Balancer"
    echo "     - CloudFront distribution"
    echo "     - VPC and networking resources"
    echo "     - RTB Fabric Responder Gateway (if deployed)"
    echo ""
fi

# Step 4: Confirmation prompt (unless --force or --dry-run)
if [ "$FORCE" = "false" ] && [ "$DRY_RUN" = "false" ]; then
    echo ""
    print_warn "This action is IRREVERSIBLE and will permanently delete all resources!"
    print_warn "All data in S3 buckets, CloudWatch logs, and EFS will be lost!"
    echo ""
    read -p "Are you sure you want to proceed? Type 'yes' to confirm: " CONFIRMATION
    
    if [ "$CONFIRMATION" != "yes" ]; then
        print_info "Destruction cancelled by user"
        exit 0
    fi
    echo ""
fi

if [ "$DRY_RUN" = "true" ]; then
    print_info "Dry run complete - no resources were destroyed"
    exit 0
fi

# Step 5: Destroy stacks in correct order
print_step "Starting stack destruction..."
echo ""

# Destroy PrebidServerStack first (includes RTB Fabric Requester Gateway and Link)
if [ "$PREBID_STACK_EXISTS" = "true" ]; then
    print_info "Destroying $PREBID_STACK_NAME..."
    print_info "This may take 10-15 minutes..."
    
    if aws cloudformation delete-stack --stack-name "$PREBID_STACK_NAME" "${AWS_ARGS[@]}"; then
        print_info "Stack deletion initiated for $PREBID_STACK_NAME"
        print_info "Waiting for stack deletion to complete..."
        
        if aws cloudformation wait stack-delete-complete --stack-name "$PREBID_STACK_NAME" "${AWS_ARGS[@]}"; then
            print_info "Successfully destroyed $PREBID_STACK_NAME"
        else
            print_error "Failed to destroy $PREBID_STACK_NAME"
            print_error "Check CloudFormation console for details"
            exit 1
        fi
    else
        print_error "Failed to initiate deletion of $PREBID_STACK_NAME"
        print_error "Check CloudFormation console for details"
        exit 1
    fi
    echo ""
fi

# Destroy BidderSimulatorStack (includes RTB Fabric Responder Gateway)
if [ "$SIMULATOR_STACK_EXISTS" = "true" ]; then
    print_info "Destroying $SIMULATOR_STACK_NAME..."
    print_info "This may take 5-10 minutes..."
    
    if aws cloudformation delete-stack --stack-name "$SIMULATOR_STACK_NAME" "${AWS_ARGS[@]}"; then
        print_info "Stack deletion initiated for $SIMULATOR_STACK_NAME"
        print_info "Waiting for stack deletion to complete..."
        
        if aws cloudformation wait stack-delete-complete --stack-name "$SIMULATOR_STACK_NAME" "${AWS_ARGS[@]}"; then
            print_info "Successfully destroyed $SIMULATOR_STACK_NAME"
        else
            print_error "Failed to destroy $SIMULATOR_STACK_NAME"
            print_error "Check CloudFormation console for details"
            exit 1
        fi
    else
        print_error "Failed to initiate deletion of $SIMULATOR_STACK_NAME"
        print_error "Check CloudFormation console for details"
        exit 1
    fi
    echo ""
fi

# Step 6: Verify all stacks are destroyed
print_step "Verifying stack destruction..."

VERIFICATION_FAILED="false"

if aws cloudformation describe-stacks --stack-name "$PREBID_STACK_NAME" "${AWS_ARGS[@]}" > /dev/null 2>&1; then
    print_error "$PREBID_STACK_NAME still exists!"
    VERIFICATION_FAILED="true"
fi

if aws cloudformation describe-stacks --stack-name "$SIMULATOR_STACK_NAME" "${AWS_ARGS[@]}" > /dev/null 2>&1; then
    print_error "$SIMULATOR_STACK_NAME still exists!"
    VERIFICATION_FAILED="true"
fi

if [ "$VERIFICATION_FAILED" = "true" ]; then
    print_error "Stack destruction verification failed"
    print_error "Some stacks may still exist - check CloudFormation console"
    exit 1
fi

# Step 7: Success message
echo ""
print_info "=========================================="
print_info "All stacks successfully destroyed!"
print_info "=========================================="
echo ""
print_info "Destroyed resources:"
if [ "$PREBID_STACK_EXISTS" = "true" ]; then
    print_info "  ✓ $PREBID_STACK_NAME"
fi
if [ "$SIMULATOR_STACK_EXISTS" = "true" ]; then
    print_info "  ✓ $SIMULATOR_STACK_NAME"
fi
echo ""
print_info "Note: Some resources may have retention policies:"
print_info "  - S3 buckets with versioning may retain deleted objects"
print_info "  - CloudWatch log groups may be retained based on retention settings"
print_info "  - Check AWS console to verify complete cleanup if needed"
echo ""
