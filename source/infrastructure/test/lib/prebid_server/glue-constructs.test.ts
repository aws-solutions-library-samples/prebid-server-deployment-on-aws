// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the Glue database-name mechanical property change (task 7.5:
// `glue-constructs.ts`).
//
// Scope (Stage 2a verification notes, task 7.5, "Applied — prebid_glue_constructs.py"):
// Mainline changed the Glue database name from a `Aws.STACK_NAME`-prefixed name
// to a fixed lowercase prefix `prebid-server-${Aws.REGION}-${id}-database`
// (STACK_NAME can gain uppercase suffixes in nested-stack deployments; Glue DB
// names must be lowercase). The single `glueDatabaseName` variable feeds the
// Glue Database (DatabaseInput.Name), all Glue Tables (DatabaseName), and the
// Glue Job `--DATABASE_NAME` default argument. The construct id is "MetricsEtl",
// so the synthesized name is `prebid-server-<region>-metricsetl-database`.
//
// This construct is not covered by any other suite, so both presence and
// property assertions here are net-new (no overlap with the 7.9 suite).

import { Template } from "aws-cdk-lib/assertions";
import { PrebidServerStack } from "../../../lib/prebid_server/prebid-server-stack";
import { appWithCdkContext } from "../../test-helpers";

let template: Template;

// The database name is region-parameterized: `prebid-server-${AWS::Region}-metricsetl-database`.
type JoinParts = Array<string | { Ref: string }>;
const DATABASE_NAME: { "Fn::Join": [string, JoinParts] } = {
  "Fn::Join": ["", ["prebid-server-", { Ref: "AWS::Region" }, "-metricsetl-database"]],
};

beforeAll(() => {
  const app = appWithCdkContext();
  const stack = new PrebidServerStack(app, PrebidServerStack.STACK_NAME);
  template = Template.fromStack(stack);
});

describe("GlueEtl — database name reconciliation (task 7.5)", () => {
  it("synthesizes exactly one Glue database, five tables, and one job (presence)", () => {
    template.resourceCountIs("AWS::Glue::Database", 1);
    template.resourceCountIs("AWS::Glue::Table", 5);
    template.resourceCountIs("AWS::Glue::Job", 1);
  });

  it("the Glue database name is the fixed lowercase prebid-server-<region>-metricsetl-database", () => {
    template.hasResourceProperties("AWS::Glue::Database", {
      CatalogId: { Ref: "AWS::AccountId" },
      DatabaseInput: { Name: DATABASE_NAME },
    });
  });

  it("every Glue table references the same metricsetl database name", () => {
    const tables = template.findResources("AWS::Glue::Table");
    const entries = Object.entries(tables);
    expect(entries).toHaveLength(5);
    for (const [, table] of entries) {
      expect(table.Properties.DatabaseName).toEqual(DATABASE_NAME);
    }
  });

  it("the Glue job passes the metricsetl database name via --DATABASE_NAME", () => {
    template.hasResourceProperties("AWS::Glue::Job", {
      DefaultArguments: {
        "--DATABASE_NAME": DATABASE_NAME,
      },
    });
  });

  it("the database name uses lowercase literals and does not reference STACK_NAME", () => {
    // Guards the "must be lowercase" rationale: the only literal parts of the
    // Fn::Join are the lowercase prefix/suffix, and the region is the sole token
    // (AWS::Region, unlike AWS::StackName, is always lowercase). STACK_NAME —
    // which can gain uppercase suffixes in nested-stack deployments — is not used.
    const literalParts = DATABASE_NAME["Fn::Join"][1].filter(
      (p: string | { Ref: string }): p is string => typeof p === "string"
    );
    expect(literalParts).toEqual(["prebid-server-", "-metricsetl-database"]);
    for (const part of literalParts) {
      expect(part).toBe(part.toLowerCase());
    }
    expect(JSON.stringify(DATABASE_NAME)).not.toContain("AWS::StackName");
  });
});
