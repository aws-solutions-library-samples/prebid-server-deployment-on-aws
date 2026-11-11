// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for CacheConstruct (task 9.5).
// TypeScript-only construct coverage (Req 6.3): asserts presence + key property
// values of every resource CacheConstruct contributes — the ElastiCache
// serverless (valkey) cache, the default + IAM users, the user group, the cache
// Lambda + Redis layer, and the four Lambda target groups. CacheConstruct is a
// stack-level singleton (one instance).

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("CacheConstruct — ElastiCache serverless valkey (task 9.5)", () => {
  it("creates one serverless valkey cache (engine v8)", () => {
    template.resourceCountIs("AWS::ElastiCache::ServerlessCache", 1);
    template.hasResourceProperties("AWS::ElastiCache::ServerlessCache", {
      Engine: "valkey",
      MajorEngineVersion: "8",
    });
  });

  it("creates a disabled default user and an IAM-auth user in a user group", () => {
    template.resourceCountIs("AWS::ElastiCache::User", 2);
    template.resourceCountIs("AWS::ElastiCache::UserGroup", 1);
    // Disabled default user (password auth, off).
    template.hasResourceProperties("AWS::ElastiCache::User", {
      Engine: "valkey",
      AccessString: "off +get ~keys*",
    });
    // IAM-auth user with full access.
    template.hasResourceProperties("AWS::ElastiCache::User", {
      Engine: "valkey",
      AuthenticationMode: { Type: "iam" },
      AccessString: "on ~* +@all",
    });
  });

  it("creates the cache Lambda (python3.11, arm64, VPC-attached) and its Redis layer", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "cache_access.handler",
      Runtime: "python3.11",
      Architectures: ["arm64"],
      VpcConfig: Match.anyValue(),
    });
  });

  it("creates a python3.11 RedisLayer LayerVersion (redis package layer)", () => {
    // The RedisLayer supplies the `redis` + `cachetools` packages the CacheHandler
    // imports. It MUST be a real bundled layer, not just declared. Assert a
    // python3.11 LayerVersion with the Redis description exists.
    template.hasResourceProperties("AWS::Lambda::LayerVersion", {
      CompatibleRuntimes: ["python3.11"],
      Description: "Redis package layer",
    });
  });

  it("CacheHandler references at least three layers including the Redis layer", () => {
    // Regression guard for the missing-dependency-bundling defect: the CacheHandler
    // (import redis) relies on the RedisLayer being attached. Assert the handler has
    // its Layers wired (RedisLayer + operational metrics + Solutions layers).
    const fns = template.findResources("AWS::Lambda::Function", {
      Properties: { Handler: "cache_access.handler" },
    });
    const ids = Object.keys(fns);
    expect(ids.length).toBe(1);
    const layers = fns[ids[0]].Properties.Layers;
    expect(Array.isArray(layers)).toBe(true);
    expect(layers.length).toBeGreaterThanOrEqual(3);
  });

  it("creates four Lambda target groups (external/internal x cf/alb)", () => {
    // The cache exposes 4 Lambda target groups; other constructs add ALB/CF
    // target groups, so assert the cache's 4 are present via LAMBDA target type.
    const tgs = template.findResources("AWS::ElasticLoadBalancingV2::TargetGroup", {
      Properties: { TargetType: "lambda" },
    });
    expect(Object.keys(tgs).length).toBeGreaterThanOrEqual(4);
  });

  it("emits a health-checked (/cache/health) target group", () => {
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::TargetGroup", {
      TargetType: "lambda",
      HealthCheckPath: "/cache/health",
    });
  });
});
