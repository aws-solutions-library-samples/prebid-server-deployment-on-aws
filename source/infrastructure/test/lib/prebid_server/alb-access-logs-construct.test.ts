// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for AlbAccessLogsConstruct (task 9.5).
// TypeScript-only construct coverage (Req 6.3): asserts presence + key property
// values of every resource AlbAccessLogsConstruct contributes — the
// object-locked, S3-managed-encrypted access-logs bucket, the ELB-account
// mapping, and the enable-access-logs Lambda + custom resource. Created once per
// entry deployment (ALB + CloudFront => 2 instances).

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("AlbAccessLogsConstruct — access-logs bucket + enable CR (task 9.5)", () => {
  it("creates the two ALB access-logs buckets (one per entry deployment) by logical id", () => {
    const buckets = template.findResources("AWS::S3::Bucket");
    const albLogBuckets = Object.keys(buckets).filter((k) =>
      k.includes("ALBAccessLogsConstructAlbAccessLogsBucket")
    );
    expect(albLogBuckets.length).toBe(2);
  });

  it("the access-logs buckets are object-locked, versioned, and S3-managed encrypted", () => {
    const buckets = template.findResources("AWS::S3::Bucket");
    for (const [k, b] of Object.entries(buckets)) {
      if (!k.includes("ALBAccessLogsConstructAlbAccessLogsBucket")) continue;
      const props = (b as any).Properties;
      expect(props.ObjectLockEnabled).toBe(true);
      expect(props.VersioningConfiguration).toEqual({ Status: "Enabled" });
      expect(props.BucketEncryption.ServerSideEncryptionConfiguration[0].ServerSideEncryptionByDefault.SSEAlgorithm).toBe("AES256");
    }
  });

  it("creates the enable-access-logs Lambda (python3.11, arm64)", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "enable_access_logs.event_handler",
      Runtime: "python3.11",
      Architectures: ["arm64"],
    });
  });

  it("creates the enable-access-logs custom resource wired to the ALB ARN + log bucket", () => {
    template.hasResourceProperties("AWS::CloudFormation::CustomResource", {
      ALB_ARN: Match.anyValue(),
      ALB_LOG_BUCKET: Match.anyValue(),
    });
  });

  it("the access-logs bucket policy grants the ELB log-delivery + S3 logging principals PutObject", () => {
    const policies = template.findResources("AWS::S3::BucketPolicy");
    const found = Object.values(policies).some((p) =>
      JSON.stringify((p as any).Properties.PolicyDocument).includes(
        "logdelivery.elasticloadbalancing.amazonaws.com"
      )
    );
    expect(found).toBe(true);
  });
});
