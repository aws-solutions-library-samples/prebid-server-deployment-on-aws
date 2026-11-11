// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the CFN-parameter migration on PrebidServerStack (task 7.9).
//
// These assert the synthesized PrebidServerStack template against the landed
// Mainline design (the source of truth), mirroring the cfn-parameter-migration
// design's Correctness Properties / test scenarios:
//   - Property 8/9  : the 8 CloudFormation parameters + their definitions, and
//                     the absence of a SimulatorResponderGatewayId / EnableRtbFabric
//                     parameter on this stack.
//   - Property 1/2  : the HasRtbRequesterGateway / UseVpcPeering / HasSimulatorEndpoint
//                     CfnConditions and their expressions (RTB Fabric vs VPC peering).
//   - Property 3    : no Accept Lambda / no Fabric Link acceptance custom resource,
//                     and no in-CDK CfnLink (RTB Fabric Link is external).
//   - Property 4/5/6: AMT_ADAPTER_ENABLED / AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT /
//                     LOG_ANALYTICS_ENABLED derived via Fn::If chains / param refs.
//   - Property 7    : no cross-stack Fn::ImportValue references.
//
// The stack synthesizes with the cdk.json feature flags seeded via test-helpers.

import { Template } from "aws-cdk-lib/assertions";
import { PrebidServerStack } from "../../../lib/prebid_server/prebid-server-stack";
import { appWithCdkContext } from "../../test-helpers";

let template: Template;
let json: any;

beforeAll(() => {
  const app = appWithCdkContext();
  const stack = new PrebidServerStack(app, PrebidServerStack.STACK_NAME);
  template = Template.fromStack(stack);
  json = template.toJSON();
});

describe("PrebidServerStack — CloudFormation parameters (Property 8/9)", () => {
  it("defines EnableLogAnalytics (String, default 'false', allowed true/false)", () => {
    template.hasParameter("EnableLogAnalytics", {
      Type: "String",
      Default: "false",
      AllowedValues: ["true", "false"],
    });
  });

  it("defines EnableRtbRequesterGateway (String, default 'false', allowed true/false)", () => {
    template.hasParameter("EnableRtbRequesterGateway", {
      Type: "String",
      Default: "false",
      AllowedValues: ["true", "false"],
    });
  });

  it("defines ContainerImageUri (String, default '')", () => {
    template.hasParameter("ContainerImageUri", { Type: "String", Default: "" });
  });

  it("defines the VPC-peering fallback parameters (String, default '')", () => {
    for (const p of [
      "SimulatorVpcId",
      "SimulatorAlbSgId",
      "SimulatorRouteTableId1",
      "SimulatorRouteTableId2",
      "SimulatorEndpoint",
    ]) {
      template.hasParameter(p, { Type: "String", Default: "" });
    }
  });

  it("does NOT define a SimulatorResponderGatewayId parameter (link is external)", () => {
    const params = (json.Parameters ?? {}) as Record<string, unknown>;
    expect(Object.keys(params)).not.toContain("SimulatorResponderGatewayId");
  });

  it("does NOT define an EnableRtbFabric parameter on PrebidServerStack", () => {
    const params = (json.Parameters ?? {}) as Record<string, unknown>;
    expect(Object.keys(params)).not.toContain("EnableRtbFabric");
  });

  it("registers the four parameter groups in the CloudFormation Interface metadata", () => {
    const groups: Array<{ Label: { default: string }; Parameters: string[] }> =
      json.Metadata["AWS::CloudFormation::Interface"].ParameterGroups;
    const labels = groups.map((g) => g.Label.default);
    expect(labels).toEqual(
      expect.arrayContaining([
        "Container Settings",
        "Log Analytics Settings",
        "RTB Fabric Settings",
        "VPC Peering Settings (Fallback)",
      ])
    );
    const containerGroup = groups.find((g) => g.Label.default === "Container Settings")!;
    expect(containerGroup.Parameters).toContain("ContainerImageUri");
  });
});

describe("PrebidServerStack — CfnConditions (Property 1/2)", () => {
  it("HasRtbRequesterGateway == (EnableRtbRequesterGateway == 'true')", () => {
    template.hasCondition("HasRtbRequesterGateway", {
      "Fn::Equals": [{ Ref: "EnableRtbRequesterGateway" }, "true"],
    });
  });

  it("UseVpcPeering == NOT(SimulatorVpcId == '')", () => {
    template.hasCondition("UseVpcPeering", {
      "Fn::Not": [{ "Fn::Equals": [{ Ref: "SimulatorVpcId" }, ""] }],
    });
  });

  it("HasSimulatorEndpoint == NOT(SimulatorEndpoint == '')", () => {
    template.hasCondition("HasSimulatorEndpoint", {
      "Fn::Not": [{ "Fn::Equals": [{ Ref: "SimulatorEndpoint" }, ""] }],
    });
  });

  it("does NOT define a HasSimulatorFabricLink condition (link is external)", () => {
    const conditions = (json.Conditions ?? {}) as Record<string, unknown>;
    expect(Object.keys(conditions)).not.toContain("HasSimulatorFabricLink");
  });

  it("gates the RTB Fabric Requester Gateway with HasRtbRequesterGateway", () => {
    template.resourceCountIs("AWS::RTBFabric::RequesterGateway", 1);
    const gws = template.findResources("AWS::RTBFabric::RequesterGateway");
    expect((Object.values(gws)[0] as any).Condition).toBe("HasRtbRequesterGateway");
  });

  it("gates the VPC peering connection + routes + ingress with UseVpcPeering", () => {
    const peering = template.findResources("AWS::EC2::VPCPeeringConnection");
    expect(Object.keys(peering).length).toBe(1);
    expect((Object.values(peering)[0] as any).Condition).toBe("UseVpcPeering");

    // The standalone CfnSecurityGroupIngress for the bidder ALB is UseVpcPeering-gated.
    const ingresses = template.findResources("AWS::EC2::SecurityGroupIngress");
    const gated = Object.values(ingresses).filter((r: any) => r.Condition === "UseVpcPeering");
    expect(gated.length).toBeGreaterThanOrEqual(1);

    // Every peering route is gated by UseVpcPeering.
    const routes = template.findResources("AWS::EC2::Route", {
      Properties: { VpcPeeringConnectionId: {} },
    });
    for (const r of Object.values(routes)) {
      expect((r as any).Condition).toBe("UseVpcPeering");
    }
  });
});

describe("PrebidServerStack — no in-CDK Fabric Link / Accept Lambda (Property 3)", () => {
  it("contains no RTB Fabric Link resource (managed externally)", () => {
    template.resourceCountIs("AWS::RTBFabric::Link", 0);
  });

  it("contains no AcceptFabricLink / AcceptLink Lambda or custom resource", () => {
    const serialized = JSON.stringify(json);
    expect(serialized).not.toContain("AcceptFabricLink");
    expect(serialized).not.toContain("AcceptLink");
  });
});

describe("PrebidServerStack — ECS env-var derivation (Property 4/5/6)", () => {
  function taskDefEnv(): any[] {
    const taskDefs = template.findResources("AWS::ECS::TaskDefinition");
    const first = Object.values(taskDefs)[0] as any;
    return first.Properties.ContainerDefinitions[0].Environment as any[];
  }

  function envValue(name: string): any {
    const env = taskDefEnv().find((e) => e.Name === name);
    expect(env).toBeDefined();
    return env.Value;
  }

  it("AMT_ADAPTER_ENABLED = Fn::If(HasSimulatorEndpoint, 'true', 'false')", () => {
    expect(envValue("AMT_ADAPTER_ENABLED")).toEqual({
      "Fn::If": ["HasSimulatorEndpoint", "true", "false"],
    });
  });

  it("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT = Fn::If(HasSimulatorEndpoint, SimulatorEndpoint, placeholder)", () => {
    expect(envValue("AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT")).toEqual({
      "Fn::If": ["HasSimulatorEndpoint", { Ref: "SimulatorEndpoint" }, "https://localhost/not-configured"],
    });
  });

  it("LOG_ANALYTICS_ENABLED references the EnableLogAnalytics parameter directly", () => {
    expect(envValue("LOG_ANALYTICS_ENABLED")).toEqual({ Ref: "EnableLogAnalytics" });
  });
});

describe("PrebidServerStack — no cross-stack references (Property 7)", () => {
  it("contains no Fn::ImportValue references", () => {
    expect(JSON.stringify(json)).not.toContain("Fn::ImportValue");
  });
});
