// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the S3 bucket ACL fix for CDK 2.236+ (task 7.4,
// `prebid-server-stack.ts`).
//
// Scope (Stage 2a verification notes, task 7.4): the two stack-owned buckets —
// `StoredRequestsAccessLogsBucket` (createAccessLogsBucket) and the
// stored-requests `Bucket` (createStoredRequestsBucket) — must switch to
// bucket-owner-enforced ownership (ACLs disabled), so each emits
// `OwnershipControls.Rules[0].ObjectOwnership = "BucketOwnerEnforced"` with NO
// `AccessControl` property. The other stack buckets (ConfigFiles, Artifacts,
// MetricsEtl source/analytics/output, CloudTrail, CloudFront/ALB access logs)
// intentionally retain the ACL-based `ObjectWriter` + `BucketOwnerFullControl`
// posture, which is out of scope for this fix and must not regress.
//
// These assertions cover presence (resourceCountIs across the bucket set) and
// the property values (OwnershipControls / AccessControl) of every bucket the
// stack contributes. They do not overlap the cfn-parameter-migration suite (7.9).

import { Match, Template } from "aws-cdk-lib/assertions";
import { PrebidServerStack } from "../../../lib/prebid_server/prebid-server-stack";
import { appWithCdkContext } from "../../test-helpers";

let template: Template;

beforeAll(() => {
  const app = appWithCdkContext();
  const stack = new PrebidServerStack(app, PrebidServerStack.STACK_NAME);
  template = Template.fromStack(stack);
});

// Logical-ID stems (hash-suffix normalized) for the two stack-owned buckets that
// the ACL fix targets.
const ENFORCED_BUCKET_STEMS = [
  /^StoredRequestsAccessLogsBucket/,
  /^Bucket[0-9A-F]{8}$/,
];

/** Buckets whose logical ID matches one of the bucket-owner-enforced stems. */
function enforcedBuckets(buckets: Record<string, any>): Array<[string, any]> {
  return Object.entries(buckets).filter(([id]) =>
    ENFORCED_BUCKET_STEMS.some((re) => re.test(id))
  );
}

describe("PrebidServerStack — S3 bucket ACL fix for CDK 2.236+ (task 7.4)", () => {
  it("synthesizes the full stack bucket set (presence)", () => {
    // 11 buckets total in the PrebidServerStack template (2 stack-owned +
    // 9 construct-owned). Asserting the count guards against a bucket being
    // dropped or duplicated while the ACL fix is applied.
    template.resourceCountIs("AWS::S3::Bucket", 11);
  });

  it("the two stack-owned buckets use BucketOwnerEnforced and drop AccessControl", () => {
    const buckets = template.findResources("AWS::S3::Bucket");
    const enforced = enforcedBuckets(buckets);

    // Exactly the access-logs bucket and the stored-requests bucket.
    expect(enforced).toHaveLength(2);

    for (const [, bucket] of enforced) {
      expect(bucket.Properties.OwnershipControls).toEqual({
        Rules: [{ ObjectOwnership: "BucketOwnerEnforced" }],
      });
      // ACLs disabled: no canned AccessControl on the bucket-owner-enforced path.
      expect(bucket.Properties.AccessControl).toBeUndefined();
    }
  });

  it("StoredRequestsAccessLogsBucket emits BucketOwnerEnforced ownership (hasResourceProperties)", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      OwnershipControls: { Rules: [{ ObjectOwnership: "BucketOwnerEnforced" }] },
      AccessControl: Match.absent(),
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          { ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" } },
        ],
      },
      LifecycleConfiguration: Match.objectLike({
        Rules: Match.arrayWith([Match.objectLike({ Id: "AccessLogsLifecycle" })]),
      }),
    });
  });

  it("the stored-requests Bucket emits BucketOwnerEnforced ownership + server access logging (hasResourceProperties)", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      OwnershipControls: { Rules: [{ ObjectOwnership: "BucketOwnerEnforced" }] },
      AccessControl: Match.absent(),
      LoggingConfiguration: {
        LogFilePrefix: "stored-requests-bucket-logs/",
      },
    });
  });

  it("the remaining buckets retain ObjectWriter + BucketOwnerFullControl (out of scope for the fix)", () => {
    const buckets = template.findResources("AWS::S3::Bucket");
    const others = Object.entries(buckets).filter(
      ([id]) => !ENFORCED_BUCKET_STEMS.some((re) => re.test(id))
    );

    // 9 construct-owned buckets keep the legacy ACL-based posture.
    expect(others).toHaveLength(9);

    for (const [, bucket] of others) {
      expect(bucket.Properties.OwnershipControls).toEqual({
        Rules: [{ ObjectOwnership: "ObjectWriter" }],
      });
      expect(bucket.Properties.AccessControl).toBe("BucketOwnerFullControl");
    }
  });

  it("no bucket-owner-enforced bucket also carries a canned ACL (mutual exclusivity)", () => {
    const buckets = template.findResources("AWS::S3::Bucket");
    for (const bucket of Object.values(buckets)) {
      const ownership =
        (bucket as any).Properties?.OwnershipControls?.Rules?.[0]?.ObjectOwnership;
      if (ownership === "BucketOwnerEnforced") {
        expect((bucket as any).Properties.AccessControl).toBeUndefined();
      }
    }
  });
});
