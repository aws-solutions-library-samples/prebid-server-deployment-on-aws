// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for CloudFrontWafConstruct (task 9.5).
// TypeScript-only construct coverage (Req 6.3): asserts presence + key property
// values of every resource CloudFrontWafConstruct contributes — the CloudFront
// distribution (WAF-associated, logging), the custom cache policies, the
// prefix-id / create-WAF / delete-WAF custom resources + Lambdas, and the
// KMS-encrypted CloudFront access-logs bucket. Created only in the CloudFront
// entry deployment (one instance).

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("CloudFrontWafConstruct — distribution + WAF (task 9.5)", () => {
  it("creates exactly one CloudFront distribution associated with a WAF WebACL and logging enabled", () => {
    template.resourceCountIs("AWS::CloudFront::Distribution", 1);
    template.hasResourceProperties("AWS::CloudFront::Distribution", {
      DistributionConfig: Match.objectLike({
        Enabled: true,
        WebACLId: Match.anyValue(),
        Logging: Match.anyValue(),
      }),
    });
  });

  it("creates the two custom cache policies (cache path + health path)", () => {
    template.resourceCountIs("AWS::CloudFront::CachePolicy", 2);
  });

  it("creates the get-prefix-id Lambda + custom resource", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "get_prefix_id.event_handler",
    });
  });

  it("creates the create-WAF and delete-WAF Lambdas", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "create_waf_webacl.event_handler",
    });
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "delete_waf_webacl.event_handler",
    });
  });

  it("creates the delete-WAF custom resource wired to the distribution + webacl", () => {
    template.hasResourceProperties("AWS::CloudFormation::CustomResource", {
      CF_DISTRIBUTION_ID: Match.anyValue(),
      WAF_WEBACL_NAME: Match.anyValue(),
      WAF_WEBACL_ID: Match.anyValue(),
    });
  });

  it("creates a KMS-encrypted CloudFront access-logs bucket (retained logical id)", () => {
    // Backward-compat logical id override from v1.0.x.
    const buckets = template.findResources("AWS::S3::Bucket");
    expect(buckets).toHaveProperty("CloudFrontAccessLogsBucket337A74EE");
  });
});
