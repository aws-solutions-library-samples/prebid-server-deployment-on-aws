// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Shared test helpers. The product stacks depend on CDK feature flags declared
// in cdk.json (e.g. `@aws-cdk/aws-s3:serverAccessLogsUseBucketPolicy`, which
// makes self-logging buckets use a bucket policy instead of an ACL). A bare
// `new App()` does not read cdk.json, so tests must seed the App context with
// those flags — otherwise construction throws `CannotEnableLogDeliveryBucket`,
// matching how `cdk synth` (which reads cdk.json) behaves.

import { App } from "aws-cdk-lib";
import * as fs from "fs";
import * as path from "path";

let cachedContext: Record<string, unknown> | undefined;

function loadCdkContext(): Record<string, unknown> {
  if (cachedContext) return cachedContext;
  const cdkJsonPath = path.resolve(__dirname, "..", "cdk.json");
  const parsed = JSON.parse(fs.readFileSync(cdkJsonPath, "utf-8"));
  cachedContext = (parsed.context ?? {}) as Record<string, unknown>;
  return cachedContext;
}

/**
 * Create a CDK App seeded with the cdk.json context (feature flags + solution
 * metadata). Additional context entries can be merged/overridden via `extra`.
 */
export function appWithCdkContext(extra: Record<string, unknown> = {}): App {
  return new App({ context: { ...loadCdkContext(), ...extra } });
}

import { Template } from "aws-cdk-lib/assertions";
import { PrebidServerStack } from "../lib/prebid_server/prebid-server-stack";

let cachedPrebidTemplate: Template | undefined;

/**
 * Synthesize PrebidServerStack once and return the shared Template for
 * resource/property assertions. Construct-level parity tests assert against the
 * full synthesized template (the same approach as Mainline's
 * `test_prebid_server_template.py`), because several constructs (cache, DataSync
 * tasks, CloudFront/WAF, EFS) have deep cross-construct dependencies that are
 * only wired up inside the entry deployments.
 *
 * Note: the stack instantiates the per-entry-deployment constructs twice (once
 * for the ALB entry deployment, once for the CloudFront entry deployment), so
 * per-deployment resources (EFS, ECS task/service, DataSync tasks, ALB access
 * logs) appear with a count of 2. Stack-level singleton constructs (VPC,
 * Artifacts, Cache, CloudTrail, operational metrics, Glue, container image)
 * appear once.
 */
export function prebidServerTemplate(): Template {
  if (cachedPrebidTemplate) return cachedPrebidTemplate;
  const app = appWithCdkContext();
  const stack = new PrebidServerStack(app, PrebidServerStack.STACK_NAME);
  cachedPrebidTemplate = Template.fromStack(stack);
  return cachedPrebidTemplate;
}
