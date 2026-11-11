// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { App, Stack } from "aws-cdk-lib";
import { Bucket } from "aws-cdk-lib/aws-s3";
import { Template } from "aws-cdk-lib/assertions";

/**
 * Smoke test for the TypeScript CDK test harness (jest + ts-jest).
 *
 * This proves the harness runs end to end: ts-jest compiles TypeScript,
 * aws-cdk-lib loads, a stack is instantiated, and Template.fromStack
 * synthesizes it and exposes assertions. It deliberately uses a minimal,
 * self-contained stack so the harness proof does not depend on parity work
 * that is still outstanding (the product stacks currently require the demo
 * asset from Stage 1 and the S3 ACL fix from Stage 2a to synthesize).
 * Per-construct synthesis tests for the real stacks are added by tasks 7.6
 * and 9.5.
 */
describe("TypeScript CDK test harness (smoke)", () => {
  it("instantiates a stack and synthesizes it via Template.fromStack", () => {
    const app = new App();
    const stack = new Stack(app, "HarnessSmokeStack");
    new Bucket(stack, "SmokeBucket");

    const template = Template.fromStack(stack);

    template.resourceCountIs("AWS::S3::Bucket", 1);
  });
});
