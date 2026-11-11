// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { Function as LambdaFunction, InlineCode, Runtime } from "aws-cdk-lib/aws-lambda";

/**
 * Smoke test for the TypeScript CDK test harness (jest + ts-jest).
 *
 * Mirrors the lib/bidder_simulator/ tree and proves the harness runs for this
 * subtree. Uses a minimal, self-contained stack so the harness proof does not
 * depend on the demo website asset that Stage 1 (task 5.1) still needs to add.
 * The real BidderSimulatorStack synthesis test is added by tasks 7.6 / 9.5.
 */
describe("bidder_simulator harness (smoke)", () => {
  it("instantiates a stack and synthesizes it via Template.fromStack", () => {
    const app = new App();
    const stack = new Stack(app, "BidderSimulatorSmokeStack");
    new LambdaFunction(stack, "SmokeFn", {
      runtime: Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: new InlineCode("exports.handler = async () => {};"),
    });

    const template = Template.fromStack(stack);

    template.resourceCountIs("AWS::Lambda::Function", 1);
  });
});
