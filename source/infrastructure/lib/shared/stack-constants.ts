// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as path from "path";

import * as fs from "fs";

// Resolve package root by walking up from __dirname until we find package.json
function findPackageRoot(dir: string): string {
  if (fs.existsSync(path.join(dir, "package.json"))) return dir;
  const parent = path.dirname(dir);
  if (parent === dir) throw new Error("Could not find package root");
  return findPackageRoot(parent);
}
const PKG_ROOT = findPackageRoot(__dirname);
export { PKG_ROOT };

// Repo source root (`source/`) — one level above the CDK package root
// (`source/infrastructure`). Assets that are NOT part of the CDK package but
// live elsewhere under `source/` must be resolved against this, not PKG_ROOT.
// In particular the bidder simulator's `loadtest/...` assets live under
// `source/loadtest`, so they resolve as SOURCE_ROOT/loadtest/... — NOT under
// the CDK package dir. The `prebid_server/...` and `custom_resources` assets do
// live under the CDK package and must keep resolving against PKG_ROOT.
export const SOURCE_ROOT = path.dirname(PKG_ROOT);

// Path to custom resources for the CDK stack
export const CUSTOM_RESOURCES_PATH = path.join(PKG_ROOT, "custom_resources");

/**
 * Normalize a CDK context value to a boolean. Context can arrive as the string
 * "true" (the common case: deploy.sh / cdk.json pass strings) OR as a real
 * boolean (e.g. a boolean literal in cdk.json or a programmatic `App`
 * context). app.ts and prebid-server-stack.ts both read deployBiddingSimulator,
 * so they MUST interpret it identically — otherwise app.ts could skip
 * synthesizing BiddingServerSimulator while PrebidServerStack still builds the
 * bidder-enabled container image, producing a mismatched deployment.
 */
export function isContextTrue(value: unknown): boolean {
  return value === true || value === "true";
}

// HTTP header names
export const X_SECRET_HEADER_NAME = "X-Header-Secret";

// VPC and networking
export const PVT_SUBNET_NAME = "Prebid-Private";
export const PUB_SUBNET_NAME = "Prebid-Public";
export const VPC_CIDR = "10.8.0.0/16";
export const CIDR_MASK = 20;
export const MAX_AZS = 2;
export const NAT_GATEWAYS = 2;

// Container
export const CONTAINER_PORT = 8443;
export const MEMORY_LIMIT_MIB = 4096;
export const VCPU = 2048;

// Health check
export const HEALTH_URL_DOMAIN = `https://localhost:${CONTAINER_PORT}`;
export const HEALTH_PATH = "/status";
export const HEALTH_ENDPOINT = `${HEALTH_URL_DOMAIN}${HEALTH_PATH}`;
export const HEALTH_CHECK_INTERVAL_SECS = 60;
export const HEALTH_CHECK_TIMEOUT_SECS = 5;

// EFS
export const EFS_VOLUME_NAME = "prebid-efs-volume";
export const EFS_PORT = 2049;
export const EFS_MOUNT_PATH = "/mnt/efs";
export const EFS_METRICS = "metrics";
export const EFS_LOGS = "logs";
export const EFS_ANALYTICS = "analytics";

// Auto-scaling
export const CPU_TARGET_UTILIZATION_PCT = 66;
export const MEMORY_TARGET_UTILIZATION_PCT = 50;
export const SCALE_OUT_COOLDOWN_SECS = 60;
export const SCALE_IN_COOLDOWN_SECS = 100;
export const TASK_MIN_CAPACITY = 2;
export const TASK_MAX_CAPACITY = 300;
export const REQUESTS_PER_TARGET_THRESHOLD = 5000;
export const SPOT_INSTANCE_WEIGHT = 1;
export const FARGATE_RESERVED_WEIGHT = 1;

// DataSync
export const DATASYNC_METRICS_SCHEDULE = "cron(30 * * * ? *)";
export const DATASYNC_ANALYTICS_SCHEDULE = "cron(30 * * * ? *)";
export const DATASYNC_REPORT_LIFECYCLE_DAYS = 1;

// Glue
export const GLUE_MAX_CONCURRENT_RUNS = 10;
export const GLUE_TIMEOUT_MINS = 120;
export const GLUE_ATHENA_OUTPUT_LIFECYCLE_DAYS = 1;

// CloudFront
export const RESPONSE_HEADERS_POLICY_ID = "eaab4381-ed33-4a86-88ca-d9558dc6cd63";

// CloudWatch
export const CLOUDWATCH_ALARM_TYPE = "AWS::CloudWatch::Alarm";
export const CLOUDWATCH_ALARM_NAMESPACE = "AWS/ApplicationELB";
export const ANOMALY_DETECTION_BAND_2 = "ANOMALY_DETECTION_BAND(m1, 2)";
export const CLOUDFRONT_NAMESPACE = "AWS/CloudFront";
export const RESOURCE_NAMESPACE = "aws:ResourceAccount";

// Solution metadata
export const SOLUTION_APPLICATION_TYPE = "AWS-Solutions";
