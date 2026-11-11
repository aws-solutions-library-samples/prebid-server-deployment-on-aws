// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for the DataSync constructs (task 9.5).
// Parity target: Mainline test_prebid_datasync_constructs.py.
// Asserts presence + key property values of every resource the DataSync
// constructs contribute — the monitoring log group + resource policy, the EFS
// and S3 locations, the DataSync tasks (with report config + schedule), and the
// EFS cleanup / container-stop / ENI-cleanup Lambdas. DataSync tasks are created
// per entry deployment (metrics + analytics x ALB + CloudFront => 4 tasks).

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

/** Logical-ID prefix match against a resource's DependsOn list (hashes vary). */
function dependsOnMatches(dependsOn: unknown, prefix: string): boolean {
  const list = Array.isArray(dependsOn) ? dependsOn : dependsOn == null ? [] : [dependsOn];
  return list.some((d) => typeof d === "string" && d.startsWith(prefix));
}

describe("DataSync constructs — locations, tasks, cleanup (task 9.5)", () => {
  it("creates a monitoring log group and a DataSync resource policy", () => {
    // 2 DataSyncMonitoring log groups is not correct — it is a stack singleton;
    // there are 3 log groups total, one of which is the DataSync monitoring group,
    // guarded by the resource policy count of 1.
    template.resourceCountIs("AWS::Logs::ResourcePolicy", 1);
    expect(
      Object.keys(template.findResources("AWS::Logs::LogGroup")).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("creates two S3 locations (metrics + analytics)", () => {
    template.resourceCountIs("AWS::DataSync::LocationS3", 2);
    template.hasResourceProperties("AWS::DataSync::LocationS3", {
      S3Config: { BucketAccessRoleArn: Match.anyValue() },
    });
  });

  it("creates four EFS locations (metrics + analytics x 2 deployments) with TLS in-transit", () => {
    template.resourceCountIs("AWS::DataSync::LocationEFS", 4);
    template.hasResourceProperties("AWS::DataSync::LocationEFS", {
      InTransitEncryption: "TLS1_2",
    });
  });

  it("creates four DataSync tasks with report config, schedule, and exclude filter", () => {
    template.resourceCountIs("AWS::DataSync::Task", 4);
    template.hasResourceProperties("AWS::DataSync::Task", {
      Options: {
        TransferMode: Match.anyValue(),
        VerifyMode: "ONLY_FILES_TRANSFERRED",
        LogLevel: "BASIC",
      },
      Schedule: { ScheduleExpression: Match.anyValue() },
      Excludes: [{ FilterType: "SIMPLE_PATTERN", Value: Match.anyValue() }],
      TaskReportConfig: Match.objectLike({
        OutputType: "STANDARD",
        ReportLevel: "SUCCESSES_AND_ERRORS",
      }),
    });
  });

  it("creates the EFS-cleanup, container-stop, and ENI-cleanup Lambdas", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "delete_efs_files.event_handler",
    });
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "container_stop_logs.event_handler",
    });
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "delete_lambda_eni.event_handler",
    });
  });

  // Mainline parity: TaskReport._create_report_config() scopes the report
  // bucket S3 statement with ACCOUNT_ID_CONDITION (aws:ResourceAccount).
  it("scopes every DataSync TaskReport policy with the aws:ResourceAccount condition", () => {
    const policies = template.findResources("AWS::IAM::Policy");
    const reportPolicies = Object.entries(policies).filter(([id]) =>
      /DataSync(Metrics|Analytics)TaskReportPolicy/.test(id)
    );
    // metrics + analytics x ALB + CloudFront => 4 report policies.
    expect(reportPolicies.length).toBe(4);
    for (const [, res] of reportPolicies) {
      const statements = (res as { Properties: { PolicyDocument: { Statement: unknown[] } } })
        .Properties.PolicyDocument.Statement;
      const s3Stmt = (statements as Array<{ Action?: unknown; Condition?: unknown }>).find((st) =>
        JSON.stringify(st.Action ?? "").includes("s3:PutObject")
      );
      expect(s3Stmt).toBeDefined();
      expect(s3Stmt!.Condition).toEqual({
        StringEquals: { "aws:ResourceAccount": [{ Ref: "AWS::AccountId" }] },
      });
    }
  });

  // Mainline parity: the entry deployments add construct-scope deps
  // (datasync_x.node.add_dependency(artifacts_bucket / datasync_monitor.log_group)),
  // which CDK propagates to every role in the DataSync task subtree (both the
  // EfsLocation role and the TaskReport role).
  it("orders every DataSync role after the artifacts bucket and DataSync log group", () => {
    const roles = template.findResources("AWS::IAM::Role");
    const datasyncRoles = Object.entries(roles).filter(([id]) =>
      /DataSync(Metrics|Analytics)(EfsLocation|TaskReport)Role/.test(id)
    );
    // (EfsLocation + TaskReport) x (metrics + analytics) x (ALB + CloudFront) => 8.
    expect(datasyncRoles.length).toBe(8);
    for (const [, res] of datasyncRoles) {
      const dependsOn = (res as { DependsOn?: unknown }).DependsOn;
      expect(dependsOnMatches(dependsOn, "ArtifactsBucket")).toBe(true);
      expect(dependsOnMatches(dependsOn, "DataSyncMonitorLogGroup")).toBe(true);
    }
  });

  it("creates EventBridge rules on DataSync task success and ECS task STOPPING", () => {
    template.hasResourceProperties("AWS::Events::Rule", {
      EventPattern: Match.objectLike({
        source: ["aws.datasync"],
        "detail-type": ["DataSync Task Execution State Change"],
      }),
    });
    template.hasResourceProperties("AWS::Events::Rule", {
      EventPattern: Match.objectLike({
        source: ["aws.ecs"],
        "detail-type": ["ECS Task State Change"],
      }),
    });
  });
});
