import { PowertoolsLayer, CrHelperLayer, SolutionsLayer, pythonAssetCode } from "../shared/lambda-helpers";
// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, CustomResource, Duration } from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";
import * as path from "path";

export class OperationalMetricsConstruct extends Construct {
  public readonly operationalMetricsLayer: lambda.LayerVersion;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    const secretsPolicy = new iam.Policy(this, "OperationalMetricsLambdaIamPolicy", {
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            "secretsmanager:DescribeSecret", "secretsmanager:CreateSecret",
            "secretsmanager:DeleteSecret", "secretsmanager:UpdateSecret",
            "secretsmanager:PutSecretValue", "secretsmanager:GetSecretValue",
          ],
          resources: [`arn:aws:secretsmanager:${Aws.REGION}:${Aws.ACCOUNT_ID}:secret:${Aws.STACK_NAME}-anonymous-metrics-uuid*`],
        }),
      ],
    });

    const opsRole = new iam.Role(this, "CreateOperationalMetricsRole", {
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
    const fn = new lambda.Function(this, "CreateOperationalMetrics", {
      role: opsRole,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "ops_metrics.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "operational_metrics")),
      description: "Lambda function for custom resource for the creating anonymous operational metrics",
      timeout: Duration.minutes(5),
      memorySize: 256,
      architecture: lambda.Architecture.ARM_64,
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this), SolutionsLayer.getOrCreate(this)],
      environment: {
        SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
        SOLUTION_NAME: this.node.tryGetContext("SOLUTION_NAME") ?? "",
        SOLUTION_APPLICATION_TYPE: constants.SOLUTION_APPLICATION_TYPE,
        STACK_NAME: Aws.STACK_NAME,
        RESOURCE_PREFIX: Aws.STACK_NAME,
        METRICS_NAMESPACE: this.node.tryGetContext("METRICS_NAMESPACE") ?? "",
      },
    });
    (fn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });
    secretsPolicy.attachToRole(fn.role!);

    const cr = new CustomResource(this, "OperationalMetricsCustomResource", {
      serviceToken: fn.functionArn,
    });
    cr.node.addDependency(secretsPolicy);

    // Lambda function alarms (matches SolutionsLambdaFunctionAlarm pattern)
    const alarmScope = new Construct(this, "operational-metrics-lambda-alarm");
    new cloudwatch.Alarm(alarmScope, "operational-metrics-lambda-alarm-errors", {
      metric: fn.metricErrors({ period: Duration.minutes(1), statistic: "Average" }),
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    });
    new cloudwatch.Alarm(alarmScope, "operational-metrics-lambda-alarm-throttles", {
      metric: fn.metricThrottles({ period: Duration.minutes(1), statistic: "Average" }),
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
    });

    this.operationalMetricsLayer = new lambda.LayerVersion(this, "metrics-layer", {
      code: lambda.Code.fromAsset(path.join(constants.PKG_ROOT, "aws_lambda_layers/metrics_layer/")),
      layerVersionName: `${Aws.STACK_NAME}-metrics-layer`,
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
    });
  }
}
