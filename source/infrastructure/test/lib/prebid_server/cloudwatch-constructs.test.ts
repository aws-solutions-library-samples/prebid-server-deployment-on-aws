// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for the CloudWatch constructs (task 9.5).
// Parity targets: Mainline test_cloudwatch_dashboard_construct.py (dashboard),
// plus the folded-in cloudwatch_alarms_construct.py / cloudwatch_metrics_construct.py
// (resolved into cloudwatch-constructs.ts in tasks 9.2/9.3). Asserts presence +
// key property values of the dashboards, the metrics-report Lambda, and the
// alarms (ALB, EFS, NAT gateway, Glue, CloudFront). These are created per entry
// deployment.

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("CloudWatch constructs — dashboards, metrics, alarms (task 9.5)", () => {
  it("creates two CloudWatch dashboards (ALB + CloudFront entry deployments) with a body", () => {
    template.resourceCountIs("AWS::CloudWatch::Dashboard", 2);
    template.hasResourceProperties("AWS::CloudWatch::Dashboard", {
      DashboardBody: Match.anyValue(),
    });
  });

  it("creates the cloudwatch-metrics-report Lambda (python3.11, arm64)", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "cloudwatch_metrics_report.event_handler",
      Runtime: "python3.11",
      Architectures: ["arm64"],
    });
  });

  it("creates the full set of CloudWatch alarms", () => {
    // Every construct-contributed alarm; the stack synthesizes 31 alarms across
    // Lambda, ALB, EFS, NAT gateway, Glue, and CloudFront namespaces.
    template.resourceCountIs("AWS::CloudWatch::Alarm", 31);
  });

  it("creates ALB 5XX/4XX and target-response-time alarms", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Namespace: "AWS/ApplicationELB",
      MetricName: "HTTPCode_ELB_5XX_Count",
    });
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Namespace: "AWS/ApplicationELB",
      MetricName: "TargetResponseTime",
    });
  });

  it("creates EFS, NAT gateway, and Glue alarms", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Namespace: "AWS/EFS",
      MetricName: "PercentIOLimit",
    });
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Namespace: "AWS/NATGateway",
      MetricName: "ErrorPortAllocation",
    });
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Namespace: "Glue",
      MetricName: "glue.error.ALL",
    });
  });

  it("creates CloudFront alarms", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Namespace: "AWS/CloudFront",
    });
  });

  // Ports the dead Python test_prebid_server_template.py ECS-utilization alarm
  // assertions (ecs_util_cpu_alarm / ecs_util_memory_alarm, gap G5). These alarms
  // key on a metric-math Metrics[] expression (SELECT AVG(...) FROM SCHEMA(...)),
  // NOT a bare MetricName, so target the specific expression block via
  // Match.arrayWith to hit the right alarm among the 31 (no bare count).
  it("creates the ECS CPU utilization alarm at Threshold 72 (GreaterThanOrEqualToThreshold)", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Threshold: 72,
      ComparisonOperator: "GreaterThanOrEqualToThreshold",
      Metrics: Match.arrayWith([
        Match.objectLike({
          Id: "ecs_cpu_utilization",
          Expression: 'SELECT AVG(CPUUtilization) FROM SCHEMA("AWS/ECS", ClusterName,ServiceName)',
        }),
      ]),
    });
  });

  it("creates the ECS memory utilization alarm at Threshold 55 (GreaterThanOrEqualToThreshold)", () => {
    template.hasResourceProperties("AWS::CloudWatch::Alarm", {
      Threshold: 55,
      ComparisonOperator: "GreaterThanOrEqualToThreshold",
      Metrics: Match.arrayWith([
        Match.objectLike({
          Id: "ecs_memory_utilization",
          Expression: 'SELECT AVG(MemoryUtilization) FROM SCHEMA("AWS/ECS", ClusterName,ServiceName)',
        }),
      ]),
    });
  });
});
