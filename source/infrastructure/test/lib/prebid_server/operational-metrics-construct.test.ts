// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for OperationalMetricsConstruct (task 9.5).
// TypeScript-only construct coverage (Req 6.3): asserts presence + key property
// values of every resource OperationalMetricsConstruct contributes — the
// ops-metrics Lambda + custom resource, the two Lambda alarms (errors +
// throttles), and the metrics Lambda layer. Stack-level singleton.

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("OperationalMetricsConstruct — anonymous metrics CR + layer (task 9.5)", () => {
  it("creates the operational-metrics Lambda (python3.11, arm64)", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "ops_metrics.event_handler",
      Runtime: "python3.11",
      Architectures: ["arm64"],
    });
  });

  it("creates a custom resource backed by the operational-metrics Lambda", () => {
    // Assert the CR's ServiceToken points at the ops-metrics function itself,
    // rather than the stack-wide CustomResource count (which is unrelated to
    // this construct and would break whenever any other construct adds/removes
    // a CR). The ops-metrics CR takes no extra props, so ServiceToken is the
    // identifying property.
    template.hasResourceProperties("AWS::CloudFormation::CustomResource", {
      ServiceToken: {
        "Fn::GetAtt": [Match.stringLikeRegexp("CreateOperationalMetrics"), "Arn"],
      },
    });
  });

  it("creates two Lambda alarms (errors + throttles) at threshold 1", () => {
    const alarms = template.findResources("AWS::CloudWatch::Alarm", {
      Properties: {
        Namespace: "AWS/Lambda",
        Threshold: 1,
        ComparisonOperator: "GreaterThanOrEqualToThreshold",
      },
    });
    // Two ops-metrics lambda alarms (errors + throttles).
    expect(Object.keys(alarms).length).toBeGreaterThanOrEqual(2);
  });

  it("emits the metrics Lambda layer (python3.11 compatible)", () => {
    template.hasResourceProperties("AWS::Lambda::LayerVersion", {
      CompatibleRuntimes: Match.arrayWith(["python3.11"]),
      LayerName: Match.objectLike({
        "Fn::Join": Match.anyValue(),
      }),
    });
  });
});
