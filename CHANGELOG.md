# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-11-09

### Changed
- **Migrated the CDK application from Python to TypeScript.** All infrastructure constructs
  (VPC, ECS Fargate, CloudFront, WAF, EFS, ElastiCache, Glue ETL, DataSync, the metrics data
  layer, RTB Fabric integration, and the bidder simulator) are now authored in TypeScript CDK.
  The Python CDK application and its constructs have been removed. This is a breaking change to
  the build and deployment toolchain and is the reason for the major version bump; the deployed
  AWS architecture is unchanged.
- `deploy.sh` now uses the npm/npx CDK toolchain instead of the Python CDK CLI. `destroy.sh` deletes the stacks with the AWS CLI and does not require the CDK toolchain.
- The cdk-solution-helper post-processor was reimplemented in TypeScript.
- Reorganized the TypeScript CDK layout to mirror the prior Python folder structure.

### Added
- AL2023 Dockerfile variant for the Prebid Server container image, selectable via a
  `--base-image` deploy flag (alongside the existing Alpine base).
- Operational-metrics Lambda error/throttle CloudWatch alarms (ported with the full CfnResource pattern).
- `PrebidConfigsManager` wired into the container image construct.
- Reproducible builds: TypeScript constructs are compiled at build time and `package-lock.json`
  is committed; jest coverage is emitted as a Cobertura report.

### Security
- Lambda layer Python dependency CVE floors raised (urllib3, requests, Werkzeug).
- curl/libcurl upgraded to 8.22.0-r0 and musl upgraded in the container image.

### Build
- Lambda layer dependencies are pre-installed at build time; Docker bundling for Lambda layers was removed.
- `.ash` scanner artifacts excluded from the public OSS distribution package.

## [1.4.0] - 2026-06-09

### Added
- CloudFormation parameter-driven deployment (all runtime config via CFN parameters, no CDK context)
- Shell wrapper `deployment/simulator-fabric-link.sh` for RTB Fabric Link operations
- ECS stack outputs (EcsClusterName, EcsServiceName) for operational tooling
- VPC peering construct for bidding simulator connectivity (fallback for non-RTB regions)
- Finch container runtime support in deploy.sh with ECR public and private registry authentication
- Pre-built container image option via `--container-image` flag in deploy.sh
- npm-based build system for demo website with locally bundled JavaScript dependencies
- Standalone build-demo.sh script for independent demo building and testing
- Local npm serve support for demo testing (`npm run serve`)
- Migration guide (`docs/migration-guide-v1.3-to-v1.4.md`)
- VAST instream video and outstream test request files for functional testing
- Video endpoint configuration and test coverage

### Security
- **Upgraded Prebid Server Java to v3.43.0** to address GHSA-4p3g-4hcj-wpvx (Critical 10.0 CVSS — bidder adapter hostname forgery allowing SSRF)
- Upgraded Spring Boot to 3.5.14 to address CVE-2026-40973 (ApplicationTemp predictable directory hijack)
- Removed spring-framework.version override (Boot 3.5.14 manages 6.2.15+ natively)
- Updated urllib3 to >=2.6.3 to address CVE-2026-21441, CVE-2025-66471, CVE-2025-66418
- Updated Werkzeug to >=3.1.5 to address CVE-2026-21860, CVE-2025-66221
- Updated pip upgrade in build processes to address CVE-2025-8869
- Upgraded Netty to 4.2.13.Final to address CVE-2026-33870, CVE-2026-33871, CVE-2026-41417, CVE-2025-67735
- Upgraded Vert.x to 4.5.24 to address CVE-2026-1002 and CVE-2026-6860
- Upgraded musl to address CVE-2026-40200 and CVE-2026-6042
- Upgraded zlib to address CVE-2026-27171
- Bumped cryptography and Python version for CVE remediation
- Fixed CVE-2026-24515, CVE-2026-25210, CVE-2025-46394, CVE-2024-58251

### Changed
- ECS task default configuration changed to 2 vCPU / 4 GB (CPU-optimized for bid processing)
- Prebid Server Java upgraded from v3.28.0 to v3.43.0
- Spring Boot upgraded to 3.5.14 via Maven property override (aligned with PBS-Java 3.43.0 parent pom)
- Vert.x upgraded to 4.5.24 via Maven property override
- Netty upgraded to 4.2.13.Final via Maven property override
- All runtime configuration migrated from CDK context to CloudFormation parameters with CfnConditions
- Decoupled BidderSimulator and RTB Fabric Link management moved from CloudFormation custom resource to standalone Python script
- Demo website migrated from CDN dependencies to locally bundled npm packages (video.js 8.23.8, videojs-contrib-ads 7.4.0, @dailymotion/vast-client 4.0.0, in-renderer-js 1.2.3, prebid.js 10.26.0)
- Demo build integrated into deploy.sh workflow (runs automatically when DEPLOY_BIDDING_SIMULATOR=true)
- Demo HTML/JS updated to reference local vendor/ paths instead of CDN URLs
- BucketDeployment Lambda memory increased to 512 MB and exclude patterns optimized for faster deployments
- Glue database name forced to lowercase to avoid nested stack uppercase issues
- Bidder Simulator endpoint defaults to `https://localhost/not-configured` placeholder when not set
- Architecture diagram updated
- README rewritten for new deployment scenarios and container image documentation

### Fixed
- Fixed test_auction_request assertions to match updated impression IDs and bid prices
- Fixed AcceptFabricLink role default policy gated with CfnCondition
- Fixed S3 bucket ACL compatibility for CDK 2.236+
- Fixed port 8443 security group rule between ALB and ECS
- Fixed banner bid dimensions to match impression requested sizes
- Fixed demo BucketDeployment prune=False to prevent asset deletion
- Replaced inaccessible Big Buck Bunny video URL with stable W3C Sintel trailer

## [1.3.0] - 2025-02-05

### Added
- RTB Fabric integration with requester and responder gateways
- VPC peering support for bidding simulator when not using RTB Fabric
- Demo website with Prebid.js integration (banner and video ad units)
- VAST instream video support in bidder simulator
- Destroy script for stack cleanup
- Lambda functions for RTB Fabric link acceptance and gateway readiness checks
- Automated bidder simulator deployment via CDK context flag `deployBiddingSimulator`
- Automated AMT adapter configuration and Docker build integration
- Analytics adapter control via CDK context flag `enableLogAnalytics`
- Test scripts for auction validation (test-auction-amt.py)
- Example JSON files for auction request/response format

### Changed
- Refactored bidder simulator to CloudFront + ALB + Lambda architecture
- Consolidated demo_bidder and loadtest_bidder into single loadtest_bidder
- Updated AWS Lambda runtime to Python 3.11
- Replaced internal CloudFront with ALB for bidding simulator
- Updated cache Lambda bundling to use `cp -ru` instead of `cp -au`
- Fixed ElastiCache IAM provider to handle botocore weak references in Python 3.11 runtime
- AMT bidder files now conditionally included in Docker build based on deployment flag
- Environment variables automatically configured for AMT adapter and analytics
- Prebid Server configuration uses environment variable substitution for runtime settings

### Fixed
- Removed deprecated --bidder-type parameter from deploy.sh
- Fixed indentation error in bidder_simulator_stack.py
- Fixed botocore session garbage collection issue in ElastiCache IAM provider

### Removed
- Removed deprecated demo_bidder Lambda function
- Removed --bidder-type parameter from deployment scripts

## [1.2.0] - 2025-11-11

- Conversion to guidance
- Application settings storage moved to S3
- Prebid cache with ElastiCache
- HTTPS Support
- Removed AWS Service Catalog AppRegistry Integration
- Load testing and operational improvements
- Security updates

## [1.1.6] - 2025-09-19

- Pinned Netty to 4.2.5.Final
- Upgraded Spring Framework to 6.2.11
- Updated Python dependencies

## [1.1.5] - 2025-09-11

- Pinned Netty to 4.2.4.Final to address CVE-2024-47535
- Pinned Commons Lang3 to 3.18.0 to address CVE-2024-47554
- Upgraded Spring Framework to 6.2.7 and Spring Boot to 3.4.5
- Updated Alpine Docker image from 3.21 to 3.22.1

## [1.1.4] - 2025-07-30

- Upgrade Prebid Server Java to v3.28.0

## [1.1.3] - 2025-06-23

- Upgrade Prebid Server Java to v3.27.0

## [1.1.2] - 2025-05-22

- Upgrade Prebid Server Java to v3.25.0
- Upgrade Python dependencies
- Fix anonymized metrics reporting Lambda

## [1.1.1] - 2025-03-07

- Upgrade to Prebid Server v3.22 and underlying Docker base image
- Optimized container image using jlink reducing image size from 774 MB to 142 MB
- Change to Poetry for Python dependency management
- Add script to run Prebid Server container locally with stack settings

## [1.1.0] - 2024-10-31

- Upgrade to Prebid Server v3.13 and underlying Docker base image
- ECS runtime logs in AWS CloudWatch instead of S3
- Option to opt-out of installing CloudFront and WAF
- Customize Prebid Server configuration through files in S3
- Option to specify a custom container image

## [1.0.2] - 2024-09-23

- Upgrade Python `requests` package to version 2.32.3 in requirements.txt
- Bug fix for launch failure of EfsCleanupContainerStop Lambda function

## [1.0.1] - 2024-08-02

- Remove python `setuptools` and `pip` from prebid server docker image
- Include missing copyright header for `source/infrastructure/prebid_server/stack_constants.py`

## [1.0.0] - 2024-05-28

### Added

- All files, initial version
