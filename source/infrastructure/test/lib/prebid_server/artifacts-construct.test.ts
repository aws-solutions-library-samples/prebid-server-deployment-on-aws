// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for ArtifactsManager (task 9.5).
// Parity target: Mainline test_prebid_artifacts_constructs.py.
// Asserts presence + key property values of every resource ArtifactsManager
// contributes — the KMS-encrypted artifacts bucket (block-public, autoDelete,
// lifecycle rules), the upload Lambda, and the upload custom resource.

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("ArtifactsManager — artifacts bucket + upload CR (task 9.5)", () => {
  it("creates a block-public, KMS-encrypted artifacts bucket with datasync/athena lifecycle rules", () => {
    const buckets = template.findResources("AWS::S3::Bucket", {
      Properties: {
        BucketEncryption: {
          ServerSideEncryptionConfiguration: [
            {
              ServerSideEncryptionByDefault: { SSEAlgorithm: "aws:kms" },
            },
          ],
        },
        LifecycleConfiguration: {
          Rules: Match.arrayWith([
            Match.objectLike({ Prefix: "datasync" }),
            Match.objectLike({ Prefix: "athena" }),
          ]),
        },
      },
    });
    expect(Object.keys(buckets).length).toBeGreaterThanOrEqual(1);
    for (const [, b] of Object.entries(buckets)) {
      expect((b as any).Properties.PublicAccessBlockConfiguration).toEqual({
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      });
    }
  });

  it("creates the artifacts KMS key with rotation enabled", () => {
    template.hasResourceProperties("AWS::KMS::Key", { EnableKeyRotation: true });
  });

  it("creates the upload-artifacts Lambda (python3.11, arm64)", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "upload_files.event_handler",
      Runtime: "python3.11",
      Architectures: ["arm64"],
    });
  });

  it("creates the upload-artifacts custom resource wired to the bucket name", () => {
    template.hasResourceProperties("AWS::CloudFormation::CustomResource", {
      artifacts_bucket_name: Match.anyValue(),
      custom_resource_uuid: Match.anyValue(),
    });
  });

  // Operability guard: the upload custom resource sets a 5-minute ServiceTimeout.
  // Without it, a stuck custom-resource Lambda leaves CloudFormation waiting on the
  // default ~1h timeout, stalling deployments and rollbacks. serviceTimeout:
  // Duration.minutes(5) renders as ServiceTimeout "300" (seconds) on the CR.
  it("sets a 5-minute ServiceTimeout on the upload-artifacts custom resource", () => {
    const crs = template.findResources("AWS::CloudFormation::CustomResource", {
      Properties: { artifacts_bucket_name: Match.anyValue() },
    });
    const entries = Object.entries(crs);
    expect(entries.length).toBeGreaterThanOrEqual(1);
    for (const [, cr] of entries) {
      expect((cr as any).Properties.ServiceTimeout).toBe("300");
    }
  });

  it("enables S3 auto-delete on the artifacts bucket", () => {
    template.resourceCountIs("Custom::S3AutoDeleteObjects", 1);
  });
});
