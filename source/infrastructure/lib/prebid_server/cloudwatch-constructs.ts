import { SolutionsLayer, pythonAssetCode } from "../shared/lambda-helpers";
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// CloudWatch Alarms, Metrics, and Dashboard constructs
// Ported from cloudwatch_alarms_construct.py, cloudwatch_metrics_construct.py, cloudwatch_dashboard_construct.py
//
// These constructs define CloudWatch alarms, custom metrics collection, and dashboards.
// The dashboard construct (983 lines in Python) is primarily widget definitions.

import { Aws, CfnOutput, Duration, Fn } from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as efs from "aws-cdk-lib/aws-efs";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as events from "aws-cdk-lib/aws-events";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";
import * as path from "path";

export interface CloudwatchMetricsConstructProps {
  cloudFrontId?: string;
  publicSubnets: string[];
  loadBalancerFullName: string;
  elasticacheClusterId: string;
}

export class CloudwatchMetricsConstruct extends Construct {
  constructor(scope: Construct, id: string, props: CloudwatchMetricsConstructProps) {
    super(scope, id);

    const cwRole = new iam.Role(this, "CloudwatchMetricsFunctionRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      inlinePolicies: {
        LambdaFunctionServiceRolePolicy: new iam.PolicyDocument({
          statements: [new iam.PolicyStatement({
            actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            resources: [`arn:${Aws.PARTITION}:logs:${Aws.REGION}:${Aws.ACCOUNT_ID}:log-group:/aws/lambda/*`],
          })],
        }),
      },
    });
    const fn = new lambda.Function(this, "CloudwatchMetricsFunction", {
      role: cwRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "cloudwatch_metrics_report.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "cloudwatch_metrics")),
      description: "Lambda function for reporting metrics",
      timeout: Duration.minutes(5),
      memorySize: 256,
      architecture: lambda.Architecture.ARM_64,
      layers: [SolutionsLayer.getOrCreate(this)],
      environment: {
        STACK_NAME: Aws.STACK_NAME,
        SOLUTION_ID: scope.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: scope.node.tryGetContext("SOLUTION_VERSION") ?? "",
        METRICS_NAMESPACE: scope.node.tryGetContext("METRICS_NAMESPACE") ?? "",
        CF_DISTRIBUTION_ID: props.cloudFrontId ?? "",
        SUBNET_IDS: JSON.stringify(props.publicSubnets),
        LOAD_BALANCER_NAME: props.loadBalancerFullName,
        SEND_ANONYMIZED_DATA: Fn.findInMap("Solution", "Data", "SendAnonymizedData", "Yes"),
        ELASTICACHE_CLUSTER_ID: props.elasticacheClusterId,
      },
    });
    (fn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });

    fn.role!.attachInlinePolicy(new iam.Policy(this, "CloudwatchMetricsLambdaIamPolicy", {
      statements: [
        new iam.PolicyStatement({ actions: ["secretsmanager:GetSecretValue"], resources: [`arn:aws:secretsmanager:${Aws.REGION}:${Aws.ACCOUNT_ID}:secret:${Aws.STACK_NAME}-anonymous-metrics-uuid*`] }),
        new iam.PolicyStatement({ actions: ["cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics", "cloudwatch:PutMetricData"], resources: ["*"] }),
        new iam.PolicyStatement({ actions: ["ec2:DescribeNatGateways"], resources: ["*"] }),
      ],
    }));

    // Daily schedule
    const rule = new events.CfnRule(this, "CloudwatchMetricsRule", {
      description: "Send metrics daily at 5am UTC",
      scheduleExpression: "cron(0 5 * * ? *)",
      state: "ENABLED",
      targets: [{ arn: fn.functionArn, id: "send-cloudwatch-metrics" }],
    });

    new lambda.CfnPermission(this, "CloudwatchMetricsPermissions", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionArn,
      principal: "events.amazonaws.com",
      sourceArn: rule.attrArn,
    });
  }
}

export interface CloudwatchDashboardProps {
  applicationLoadBalancer: elbv2.ApplicationLoadBalancer;
  efsFileSystem: efs.FileSystem;
  vpc: ec2.IVpc;
  glueJobName: string;
  ecsClusterName: string;
  ecsServiceName: string;
  albTargetGroup: elbv2.ApplicationTargetGroup;
  cacheTargetGroup: elbv2.ApplicationTargetGroup;
  cacheAlb: elbv2.ApplicationLoadBalancer;
  dataSyncMetricsBucketName: string;
  metricsEtlBucketName: string;
  cacheLambdaName: string;
  efsCleanupLambdaName: string;
  containerStopLambdaName: string;
  glueTriggerLambdaName: string;
  elasticacheClusterId: string;
  cloudfrontDistribution?: cloudfront.Distribution;
  wafWebaclName?: string;
}

export class BaseCloudwatchDashboard extends Construct {
  protected readonly dashboard: cloudwatch.Dashboard;

  constructor(scope: Construct, id: string, props: CloudwatchDashboardProps) {
    super(scope, id);

    const p1m = Duration.minutes(1);
    const albNs = "AWS/ApplicationELB";
    const albDims = { LoadBalancer: props.applicationLoadBalancer.loadBalancerFullName };
    const cacheAlbDims = { LoadBalancer: props.cacheAlb.loadBalancerFullName };
    const ecsDims = { ClusterName: props.ecsClusterName, ServiceName: props.ecsServiceName };
    const efsDims = { FileSystemId: props.efsFileSystem.fileSystemId };
    const cacheDims = { clusterId: props.elasticacheClusterId };
    const tgDims = { LoadBalancer: props.applicationLoadBalancer.loadBalancerFullName, TargetGroup: props.albTargetGroup.targetGroupFullName };
    const cacheTgDims = { LoadBalancer: props.cacheAlb.loadBalancerFullName, TargetGroup: props.cacheTargetGroup.targetGroupFullName };
    const lambdaNames: Record<string, string> = {
      [props.cacheLambdaName]: "Cache",
      [props.efsCleanupLambdaName]: "EFS Cleanup",
      [props.containerStopLambdaName]: "Container Stop Logs",
      [props.glueTriggerLambdaName]: "Glue Trigger",
    };

    this.dashboard = new cloudwatch.Dashboard(this, "PrebidDeploymentDashboard", {
      dashboardName: `Dashboard-${Aws.STACK_NAME}-${Aws.REGION}`,
    });

    new CfnOutput(this, "DashboardUrl", {
      value: `https://${Aws.REGION}.console.aws.amazon.com/cloudwatch/home?region=${Aws.REGION}#dashboards:name=Dashboard-${Aws.STACK_NAME}-${Aws.REGION}`,
      description: "Link to the CloudWatch Dashboard",
    });

    // Hook for subclasses to add widgets before base widgets
    this.addCustomWidgets(props);

    // Public ALB section
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({ title: "Public ALB Request Count", width: 8, left: [
        new cloudwatch.Metric({ namespace: albNs, metricName: "RequestCount", dimensionsMap: albDims, statistic: "Sum", period: p1m, label: "Total Requests" }),
        new cloudwatch.Metric({ namespace: albNs, metricName: "RequestCountPerTarget", dimensionsMap: tgDims, statistic: "Sum", period: p1m, label: "Requests Per Target" }),
      ]}),
      new cloudwatch.GraphWidget({ title: "Public ALB HTTP Target Status", width: 8, left: [
        new cloudwatch.Metric({ namespace: albNs, metricName: "HTTPCode_Target_2XX_Count", dimensionsMap: albDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.GREEN }),
        new cloudwatch.Metric({ namespace: albNs, metricName: "HTTPCode_Target_3XX_Count", dimensionsMap: albDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.BLUE }),
        new cloudwatch.Metric({ namespace: albNs, metricName: "HTTPCode_Target_4XX_Count", dimensionsMap: albDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.ORANGE }),
        new cloudwatch.Metric({ namespace: albNs, metricName: "HTTPCode_Target_5XX_Count", dimensionsMap: albDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.RED }),
      ]}),
      new cloudwatch.GraphWidget({ title: "Public ALB Bytes", width: 8, region: Aws.REGION, left: [
        new cloudwatch.Metric({ namespace: albNs, metricName: "ProcessedBytes", dimensionsMap: albDims, statistic: "Sum", period: p1m, label: "Processed Bytes" }),
      ]}),
    );

    // Internal Cache ALB section
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({ title: "Internal Cache ALB Request Count", width: 8, left: [
        new cloudwatch.Metric({ namespace: albNs, metricName: "RequestCount", dimensionsMap: cacheAlbDims, statistic: "Sum", period: p1m, label: "Total Requests" }),
        new cloudwatch.Metric({ namespace: albNs, metricName: "RequestCountPerTarget", dimensionsMap: cacheTgDims, statistic: "Sum", period: p1m, label: "Requests Per Target" }),
      ]}),
      new cloudwatch.GraphWidget({ title: "Internal Cache ALB HTTP Target Status", width: 8, left: [
        new cloudwatch.Metric({ namespace: albNs, metricName: "HTTPCode_Target_2XX_Count", dimensionsMap: cacheAlbDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.GREEN }),
        new cloudwatch.Metric({ namespace: albNs, metricName: "HTTPCode_Target_3XX_Count", dimensionsMap: cacheAlbDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.BLUE }),
        new cloudwatch.Metric({ namespace: albNs, metricName: "HTTPCode_Target_4XX_Count", dimensionsMap: cacheAlbDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.ORANGE }),
        new cloudwatch.Metric({ namespace: albNs, metricName: "HTTPCode_Target_5XX_Count", dimensionsMap: cacheAlbDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.RED }),
      ]}),
      new cloudwatch.GraphWidget({ title: "Internal Cache ALB Bytes", width: 8, region: Aws.REGION, left: [
        new cloudwatch.Metric({ namespace: albNs, metricName: "ProcessedBytes", dimensionsMap: cacheAlbDims, statistic: "Sum", period: p1m, label: "Processed Bytes" }),
      ]}),
    );

    // Lambda section
    const lambdaInvocations = Object.entries(lambdaNames).map(([name, label]) =>
      new cloudwatch.Metric({ namespace: "AWS/Lambda", metricName: "Invocations", dimensionsMap: { FunctionName: name }, statistic: "Sum", period: p1m, label }));
    const lambdaErrors = Object.entries(lambdaNames).map(([name, label]) =>
      new cloudwatch.Metric({ namespace: "AWS/Lambda", metricName: "Errors", dimensionsMap: { FunctionName: name }, statistic: "Sum", period: p1m, label }));
    const lambdaDurations: cloudwatch.Metric[] = [];
    for (const [name, label] of Object.entries(lambdaNames)) {
      lambdaDurations.push(new cloudwatch.Metric({ namespace: "AWS/Lambda", metricName: "Duration", dimensionsMap: { FunctionName: name }, statistic: "Average", period: p1m, label: `${label} (Avg)` }));
      lambdaDurations.push(new cloudwatch.Metric({ namespace: "AWS/Lambda", metricName: "Duration", dimensionsMap: { FunctionName: name }, statistic: "Maximum", period: p1m, label: `${label} (Max)` }));
    }
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({ title: "Lambda Function Invocations", width: 8, left: lambdaInvocations }),
      new cloudwatch.GraphWidget({ title: "Lambda Function Errors", width: 8, left: lambdaErrors }),
      new cloudwatch.GraphWidget({ title: "Lambda Function Duration", width: 8, left: lambdaDurations }),
    );

    // NAT section
    const vpc = props.vpc as ec2.Vpc;
    const natConnections: cloudwatch.Metric[] = [];
    const natBytes: cloudwatch.Metric[] = [];
    vpc.publicSubnets.forEach((subnet, i) => {
      const natId = (subnet.node.findChild("NATGateway") as any).ref;
      natConnections.push(new cloudwatch.Metric({ namespace: "AWS/NATGateway", metricName: "ActiveConnectionCount", dimensionsMap: { NatGatewayId: natId }, statistic: "Sum", period: p1m, label: `Active Connections (NAT ${i + 1})` }));
      natBytes.push(new cloudwatch.Metric({ namespace: "AWS/NATGateway", metricName: "BytesInFromDestination", dimensionsMap: { NatGatewayId: natId }, statistic: "Sum", period: p1m, label: `Bytes In (NAT ${i + 1})` }));
      natBytes.push(new cloudwatch.Metric({ namespace: "AWS/NATGateway", metricName: "BytesOutToDestination", dimensionsMap: { NatGatewayId: natId }, statistic: "Sum", period: p1m, label: `Bytes Out (NAT ${i + 1})` }));
    });
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({ title: "NAT Gateway Connections", width: 12, left: natConnections }),
      new cloudwatch.GraphWidget({ title: "NAT Gateway Bytes", width: 12, left: natBytes }),
    );

    // ECS section
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({ title: "ECS Task Count", width: 8, left: [
        new cloudwatch.Metric({ namespace: "ECS/ContainerInsights", metricName: "RunningTaskCount", dimensionsMap: ecsDims, statistic: "Maximum", period: p1m }),
      ]}),
      new cloudwatch.GraphWidget({ title: "ECS CPU Utilization", width: 8, left: [
        new cloudwatch.Metric({ namespace: "AWS/ECS", metricName: "CPUUtilization", dimensionsMap: ecsDims, statistic: "Average", period: p1m, label: "Average" }),
        new cloudwatch.Metric({ namespace: "AWS/ECS", metricName: "CPUUtilization", dimensionsMap: ecsDims, statistic: "Maximum", period: p1m, label: "Maximum" }),
      ]}),
      new cloudwatch.GraphWidget({ title: "ECS Memory Utilization", width: 8, left: [
        new cloudwatch.Metric({ namespace: "AWS/ECS", metricName: "MemoryUtilization", dimensionsMap: ecsDims, statistic: "Average", period: p1m }),
      ]}),
    );

    // EFS section
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({ title: "EFS Data and Metadata IO", width: 12, left: [
        new cloudwatch.Metric({ namespace: "AWS/EFS", metricName: "DataReadIOBytes", dimensionsMap: efsDims, statistic: "Sum", period: p1m, label: "Data Read" }),
        new cloudwatch.Metric({ namespace: "AWS/EFS", metricName: "DataWriteIOBytes", dimensionsMap: efsDims, statistic: "Sum", period: p1m, label: "Data Write" }),
        new cloudwatch.Metric({ namespace: "AWS/EFS", metricName: "MetadataIOBytes", dimensionsMap: efsDims, statistic: "Sum", period: p1m, label: "Metadata IO" }),
      ]}),
      new cloudwatch.GraphWidget({ title: "EFS Storage Usage", width: 12, left: [
        new cloudwatch.Metric({ namespace: "AWS/EFS", metricName: "StorageBytes", dimensionsMap: { ...efsDims, StorageClass: "Total" }, statistic: "Sum", period: p1m, label: "Total" }),
        new cloudwatch.Metric({ namespace: "AWS/EFS", metricName: "StorageBytes", dimensionsMap: { ...efsDims, StorageClass: "Standard" }, statistic: "Sum", period: p1m, label: "Standard" }),
        new cloudwatch.Metric({ namespace: "AWS/EFS", metricName: "StorageBytes", dimensionsMap: { ...efsDims, StorageClass: "IA" }, statistic: "Sum", period: p1m, label: "IA" }),
      ]}),
    );

    // ElastiCache section
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({ title: "ElastiCache Hits and Misses", width: 8, height: 8, region: Aws.REGION, left: [
        new cloudwatch.Metric({ namespace: "AWS/ElastiCache", metricName: "CacheHits", dimensionsMap: cacheDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.GREEN }),
        new cloudwatch.Metric({ namespace: "AWS/ElastiCache", metricName: "CacheMisses", dimensionsMap: cacheDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.RED }),
      ]}),
      new cloudwatch.GraphWidget({ title: "ElastiCache Items", width: 8, height: 8, region: Aws.REGION, left: [
        new cloudwatch.Metric({ namespace: "AWS/ElastiCache", metricName: "CurrItems", dimensionsMap: cacheDims, statistic: "Average", period: p1m, label: "Current Items" }),
        new cloudwatch.Metric({ namespace: "AWS/ElastiCache", metricName: "CurrVolatileItems", dimensionsMap: cacheDims, statistic: "Average", period: p1m, label: "Current Volatile Items" }),
      ]}),
      new cloudwatch.GraphWidget({ title: "ElastiCache Network Traffic", width: 8, height: 8, region: Aws.REGION, left: [
        new cloudwatch.Metric({ namespace: "AWS/ElastiCache", metricName: "NetworkBytesIn", dimensionsMap: cacheDims, statistic: "Sum", period: p1m, label: "Network Bytes In" }),
        new cloudwatch.Metric({ namespace: "AWS/ElastiCache", metricName: "NetworkBytesOut", dimensionsMap: cacheDims, statistic: "Sum", period: p1m, label: "Network Bytes Out" }),
      ]}),
    );

    // S3 + Impressions section
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({ title: "S3 Bucket Storage", width: 12, region: Aws.REGION, left: [
        new cloudwatch.Metric({ namespace: "AWS/S3", metricName: "BucketSizeBytes", dimensionsMap: { BucketName: props.dataSyncMetricsBucketName, StorageType: "StandardStorage" }, statistic: "Sum", period: Duration.days(1), label: "Pre-ETL Metrics Bucket", region: Aws.REGION }),
        new cloudwatch.Metric({ namespace: "AWS/S3", metricName: "BucketSizeBytes", dimensionsMap: { BucketName: props.metricsEtlBucketName, StorageType: "StandardStorage" }, statistic: "Sum", period: Duration.days(1), label: "Post-ETL Metrics Bucket", region: Aws.REGION }),
      ]}),
      new cloudwatch.GraphWidget({ title: "Auctions", width: 12, region: Aws.REGION, left: [
        new cloudwatch.Metric({ namespace: `${Aws.STACK_NAME}-metrics`, metricName: "AuctionRequests", dimensionsMap: { "stack-name": Aws.STACK_NAME }, statistic: "Sum", period: p1m, label: "Auction Requests" }),
        new cloudwatch.Metric({ namespace: `${Aws.STACK_NAME}-metrics`, metricName: "ImpsRequested", dimensionsMap: { "stack-name": Aws.STACK_NAME }, statistic: "Sum", period: p1m, label: "Impressions Requested" }),
      ]}),
    );
  }

  /** Override in subclasses to add widgets before base widgets */
  protected addCustomWidgets(_props: CloudwatchDashboardProps): void {}
}

/**
 * Extended dashboard for CloudFront deployments — adds CF and WAF widgets.
 */
export class CloudFrontDeploymentDashboard extends BaseCloudwatchDashboard {
  constructor(scope: Construct, id: string, props: CloudwatchDashboardProps) {
    super(scope, id, props);
  }

  protected addCustomWidgets(props: CloudwatchDashboardProps): void {
    if (!props.cloudfrontDistribution || !props.wafWebaclName) return;

    const cfDistId = props.cloudfrontDistribution.distributionId;
    const cfDims = { Region: "Global", DistributionId: cfDistId };
    const wafDims = { WebACL: props.wafWebaclName, Rule: "ALL" };
    const cfNs = "AWS/CloudFront";
    const p1m = Duration.minutes(1);

    // Prepend CF/WAF widgets to the dashboard
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "WAF WebACL Requests", width: 8, region: "us-east-1",
        left: [
          new cloudwatch.Metric({ namespace: "AWS/WAFV2", metricName: "AllowedRequests", dimensionsMap: wafDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.GREEN }),
          new cloudwatch.Metric({ namespace: "AWS/WAFV2", metricName: "BlockedRequests", dimensionsMap: wafDims, statistic: "Sum", period: p1m, color: cloudwatch.Color.RED }),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: "CloudFront Requests", width: 8, region: "us-east-1",
        left: [new cloudwatch.Metric({ namespace: cfNs, metricName: "Requests", dimensionsMap: cfDims, statistic: "Sum", period: p1m })],
      }),
      new cloudwatch.GraphWidget({
        title: "CloudFront Error Rates", width: 8, region: "us-east-1",
        left: [
          new cloudwatch.Metric({ namespace: cfNs, metricName: "4xxErrorRate", dimensionsMap: cfDims, statistic: "Average", period: p1m, color: cloudwatch.Color.ORANGE }),
          new cloudwatch.Metric({ namespace: cfNs, metricName: "5xxErrorRate", dimensionsMap: cfDims, statistic: "Average", period: p1m, color: cloudwatch.Color.RED }),
          new cloudwatch.Metric({ namespace: cfNs, metricName: "TotalErrorRate", dimensionsMap: cfDims, statistic: "Average", period: p1m, color: cloudwatch.Color.BLUE }),
        ],
      }),
    );
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "CloudFront Bytes", width: 24, region: "us-east-1",
        left: [
          new cloudwatch.Metric({ namespace: cfNs, metricName: "BytesDownloaded", dimensionsMap: cfDims, statistic: "Sum", period: p1m, label: "Bytes Downloaded" }),
          new cloudwatch.Metric({ namespace: cfNs, metricName: "BytesUploaded", dimensionsMap: cfDims, statistic: "Sum", period: p1m, label: "Bytes Uploaded" }),
        ],
      }),
    );
  }
}
