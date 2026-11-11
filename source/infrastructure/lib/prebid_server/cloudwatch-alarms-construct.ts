// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { CfnResource } from "aws-cdk-lib";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as efs from "aws-cdk-lib/aws-efs";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";

function thresholdAdd10pct(x: number): number { return x + Math.floor(0.1 * x); }

export interface CloudwatchAlarmsProps {
  applicationLoadBalancer: elbv2.ApplicationLoadBalancer;
  efsFileSystem: efs.FileSystem;
  vpc: ec2.IVpc;
  glueJobName: string;
  cloudfrontDistribution?: cloudfront.Distribution;
  wafWebaclName?: string;
}

export class CloudwatchAlarms extends Construct {
  constructor(scope: Construct, id: string, props: CloudwatchAlarmsProps) {
    super(scope, id);
    const albFullName = props.applicationLoadBalancer.loadBalancerFullName;
    const fsId = props.efsFileSystem.fileSystemId;

    // ECS alarms
    new CfnResource(this, "ECSUtilizationCPUAlarm", {
      type: constants.CLOUDWATCH_ALARM_TYPE,
      properties: {
        ActionsEnabled: false, EvaluationPeriods: 1, DatapointsToAlarm: 1,
        Threshold: thresholdAdd10pct(constants.CPU_TARGET_UTILIZATION_PCT),
        ComparisonOperator: "GreaterThanOrEqualToThreshold", TreatMissingData: "notBreaching",
        Metrics: [{ Id: "ecs_cpu_utilization", Label: "ECS CPU Utilization", ReturnData: true,
          Expression: 'SELECT AVG(CPUUtilization) FROM SCHEMA("AWS/ECS", ClusterName,ServiceName)', Period: 60 }],
      },
    });
    new CfnResource(this, "ECSUtilizationMemoryAlarm", {
      type: constants.CLOUDWATCH_ALARM_TYPE,
      properties: {
        ActionsEnabled: false, EvaluationPeriods: 1, DatapointsToAlarm: 1,
        Threshold: thresholdAdd10pct(constants.MEMORY_TARGET_UTILIZATION_PCT),
        ComparisonOperator: "GreaterThanOrEqualToThreshold", TreatMissingData: "notBreaching",
        Metrics: [{ Id: "ecs_memory_utilization", Label: "ECS Memory Utilization", ReturnData: true,
          Expression: 'SELECT AVG(MemoryUtilization) FROM SCHEMA("AWS/ECS", ClusterName,ServiceName)', Period: 60 }],
      },
    });

    // ALB alarms
    const albDim = [{ Name: "LoadBalancer", Value: albFullName }];
    new CfnResource(this, "ALB5xxErrorAlarm", {
      type: constants.CLOUDWATCH_ALARM_TYPE,
      properties: {
        ActionsEnabled: false, MetricName: "HTTPCode_ELB_5XX_Count", Namespace: constants.CLOUDWATCH_ALARM_NAMESPACE,
        Statistic: "Average", Dimensions: albDim, Period: 60, EvaluationPeriods: 1, DatapointsToAlarm: 1,
        Threshold: 0, ComparisonOperator: "GreaterThanThreshold", TreatMissingData: "notBreaching",
      },
    });
    new CfnResource(this, "ALB4xxErrorAlarm", {
      type: constants.CLOUDWATCH_ALARM_TYPE,
      properties: {
        ActionsEnabled: false, MetricName: "HTTPCode_ELB_4XX_Count", Namespace: constants.CLOUDWATCH_ALARM_NAMESPACE,
        Statistic: "Average", Dimensions: albDim, Period: 60, EvaluationPeriods: 1, DatapointsToAlarm: 1,
        Threshold: 1, ComparisonOperator: "GreaterThanThreshold", TreatMissingData: "notBreaching",
      },
    });
    new CfnResource(this, "ALBTargetResponseTimeAlarm", {
      type: constants.CLOUDWATCH_ALARM_TYPE,
      properties: {
        ActionsEnabled: false, MetricName: "TargetResponseTime", Namespace: constants.CLOUDWATCH_ALARM_NAMESPACE,
        Statistic: "Average", Dimensions: albDim, Period: 60, EvaluationPeriods: 1, DatapointsToAlarm: 1,
        Threshold: 1, ComparisonOperator: "GreaterThanThreshold", TreatMissingData: "notBreaching",
      },
    });
    new CfnResource(this, "ALBRequestsAnomalyAlarm", {
      type: constants.CLOUDWATCH_ALARM_TYPE,
      properties: {
        ActionsEnabled: false, Dimensions: [], EvaluationPeriods: 1, DatapointsToAlarm: 1,
        ThresholdMetricId: "ad1", ComparisonOperator: "LessThanLowerOrGreaterThanUpperThreshold", TreatMissingData: "notBreaching",
        Metrics: [
          { Id: "m1", ReturnData: true, MetricStat: { Metric: { Namespace: constants.CLOUDWATCH_ALARM_NAMESPACE, MetricName: "RequestCount", Dimensions: albDim }, Period: 60, Stat: "Average" } },
          { Id: "ad1", Label: "RequestCount (expected)", ReturnData: true, Expression: constants.ANOMALY_DETECTION_BAND_2 },
        ],
      },
    });

    // EFS alarm
    new CfnResource(this, "EFSPercentIOLimitAlarm", {
      type: constants.CLOUDWATCH_ALARM_TYPE,
      properties: {
        ActionsEnabled: false, MetricName: "PercentIOLimit", Namespace: "AWS/EFS", Statistic: "Average",
        Dimensions: [{ Name: "FileSystemId", Value: fsId }], Period: 60, EvaluationPeriods: 1, DatapointsToAlarm: 1,
        Threshold: 100, ComparisonOperator: "GreaterThanOrEqualToThreshold", TreatMissingData: "notBreaching",
      },
    });

    // NAT alarms
    const vpc = props.vpc as ec2.Vpc;
    for (let i = 0; i < vpc.publicSubnets.length; i++) {
      const subnet = vpc.publicSubnets[i];
      const natGwId = (subnet.node.findChild("NATGateway") as any).ref;
      new CfnResource(this, `NATPortAllocationErrorAlarm${i}`, {
        type: constants.CLOUDWATCH_ALARM_TYPE,
        properties: {
          ActionsEnabled: false, MetricName: "ErrorPortAllocation", Namespace: "AWS/NATGateway", Statistic: "Sum",
          Dimensions: [{ Name: "NatGatewayId", Value: natGwId }], Period: 60, EvaluationPeriods: 1, DatapointsToAlarm: 1,
          Threshold: 0, ComparisonOperator: "GreaterThanThreshold", TreatMissingData: "notBreaching",
        },
      });
      new CfnResource(this, `NATPacketsDropCountAlarm${i}`, {
        type: constants.CLOUDWATCH_ALARM_TYPE,
        properties: {
          ActionsEnabled: false, MetricName: "PacketsDropCount", Namespace: "AWS/NATGateway", Statistic: "Sum",
          Dimensions: [{ Name: "NatGatewayId", Value: natGwId }], Period: 60, EvaluationPeriods: 1, DatapointsToAlarm: 1,
          Threshold: 0, ComparisonOperator: "GreaterThanThreshold", TreatMissingData: "notBreaching",
        },
      });
    }

    // Glue alarm
    new CfnResource(this, "GlueJobFailureAlarm", {
      type: constants.CLOUDWATCH_ALARM_TYPE,
      properties: {
        ActionsEnabled: false, MetricName: "glue.error.ALL", Namespace: "Glue", Statistic: "Sum",
        Dimensions: [{ Name: "JobName", Value: props.glueJobName }, { Name: "JobRunId", Value: "ALL" }],
        Period: 60, EvaluationPeriods: 1, DatapointsToAlarm: 1,
        Threshold: 0, ComparisonOperator: "GreaterThanThreshold", TreatMissingData: "notBreaching",
      },
    });

    // CloudFront alarms (conditional)
    if (props.cloudfrontDistribution) {
      const cfDim = [{ Name: "Region", Value: "Global" }, { Name: "DistributionId", Value: props.cloudfrontDistribution.distributionId }];
      for (const [name, metric, threshold] of [
        ["CloudFront4xxErrorRateAlarm", "4xxErrorRate", 1],
        ["CloudFront5xxErrorRateAlarm", "5xxErrorRate", 0],
        ["CloudFrontTotalErrorRateAlarm", "TotalErrorRate", 1],
      ] as [string, string, number][]) {
        new CfnResource(this, name, {
          type: constants.CLOUDWATCH_ALARM_TYPE,
          properties: {
            ActionsEnabled: false, MetricName: metric, Namespace: constants.CLOUDFRONT_NAMESPACE, Statistic: "Average",
            Dimensions: cfDim, Period: 60, EvaluationPeriods: 1, DatapointsToAlarm: 1,
            Threshold: threshold, ComparisonOperator: "GreaterThanThreshold", TreatMissingData: "notBreaching",
          },
        });
      }
      new CfnResource(this, "CloudFrontRequestsAnomalyAlarm", {
        type: constants.CLOUDWATCH_ALARM_TYPE,
        properties: {
          ActionsEnabled: false, Dimensions: [], EvaluationPeriods: 1, DatapointsToAlarm: 1,
          ThresholdMetricId: "ad1", ComparisonOperator: "LessThanLowerOrGreaterThanUpperThreshold", TreatMissingData: "notBreaching",
          Metrics: [
            { Id: "m1", ReturnData: true, MetricStat: { Metric: { Namespace: constants.CLOUDFRONT_NAMESPACE, MetricName: "Requests", Dimensions: cfDim }, Period: 60, Stat: "Average" } },
            { Id: "ad1", Label: "Requests (expected)", ReturnData: true, Expression: constants.ANOMALY_DETECTION_BAND_2 },
          ],
        },
      });
    }

    // WAF alarm (conditional)
    if (props.wafWebaclName) {
      new CfnResource(this, "WAFBlockedRequestsAnomalyAlarm", {
        type: constants.CLOUDWATCH_ALARM_TYPE,
        properties: {
          ActionsEnabled: false, Dimensions: [], EvaluationPeriods: 1, DatapointsToAlarm: 1,
          ThresholdMetricId: "ad1", ComparisonOperator: "GreaterThanUpperThreshold", TreatMissingData: "notBreaching",
          Metrics: [
            { Id: "m1", ReturnData: true, MetricStat: { Metric: { Namespace: "AWS/WAFV2", MetricName: "BlockedRequests", Dimensions: [{ Name: "WebACL", Value: props.wafWebaclName }, { Name: "Rule", Value: "ALL" }] }, Period: 60, Stat: "Average" } },
            { Id: "ad1", Label: "BlockedRequests (expected)", ReturnData: true, Expression: constants.ANOMALY_DETECTION_BAND_2 },
          ],
        },
      });
    }
  }
}
