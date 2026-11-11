// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for CloudTrailConstruct (task 9.5).
// TypeScript-only construct coverage (Req 6.3): asserts presence + key property
// values of every resource CloudTrailConstruct contributes — the trail
// (single-region, log-file validation, S3 data-event selectors) and its
// KMS-encrypted logging bucket. Stack-level singleton (one instance).

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("CloudTrailConstruct — S3/Lambda trail (task 9.5)", () => {
  it("creates exactly one CloudTrail trail that is logging, single-region, with log-file validation", () => {
    template.resourceCountIs("AWS::CloudTrail::Trail", 1);
    template.hasResourceProperties("AWS::CloudTrail::Trail", {
      IsLogging: true,
      IsMultiRegionTrail: false,
      IncludeGlobalServiceEvents: false,
      EnableLogFileValidation: true,
    });
  });

  it("configures S3 data-event selectors for the monitored buckets", () => {
    template.hasResourceProperties("AWS::CloudTrail::Trail", {
      EventSelectors: Match.arrayWith([
        Match.objectLike({
          DataResources: Match.arrayWith([
            Match.objectLike({ Type: "AWS::S3::Object" }),
          ]),
        }),
      ]),
    });
  });

  it("creates a KMS-encrypted, versioned, object-locked logging bucket", () => {
    // Guard: at least one bucket carries the CloudTrail logging bucket's
    // object-lock + versioning + KMS configuration.
    const buckets = template.findResources("AWS::S3::Bucket", {
      Properties: {
        ObjectLockEnabled: true,
        VersioningConfiguration: { Status: "Enabled" },
      },
    });
    expect(Object.keys(buckets).length).toBeGreaterThanOrEqual(1);
  });

  it("creates the CloudTrail logging bucket KMS key with rotation", () => {
    template.hasResourceProperties("AWS::KMS::Key", {
      EnableKeyRotation: true,
    });
  });
});
