// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for BidderSimulatorStack after the CFN-parameter migration:
// the EnableRtbFabric CFN parameter (default "true") + HasRtbFabric CfnCondition
// gate the Responder Gateway, its SecurityGroup, the ALB ingress rule from the
// Responder GW, and the ResponderGatewayId/ResponderGatewayArn outputs. The
// build-time includeRtbFabric boolean is removed.
//
// Mirrors the migration design's Property 10 (BSS Responder Gateway conditional).
//
// The stack's demo BucketDeployment reads assets from SOURCE_ROOT/loadtest/demo
// (i.e. source/loadtest/demo). The `assets/` dir is tracked in git, but the
// webpack output `dist/` is gitignored and absent on a fresh CI checkout. We
// ensure an empty `dist/` exists so synth is self-contained (mirrors mainline's
// run-unit-tests.sh `mkdir -p .../loadtest/demo/dist`). We do not populate it —
// the real build output is produced by the demo `npm run build` in deploy/CI.

import { Match, Template } from "aws-cdk-lib/assertions";
import * as fs from "fs";
import * as path from "path";
import { BidderSimulatorStack } from "../../../lib/bidder_simulator/bidder-simulator-stack";
import { appWithCdkContext } from "../../test-helpers";

const PKG_ROOT = path.resolve(__dirname, "../../..");
const SOURCE_ROOT = path.dirname(PKG_ROOT);
const DEMO_DIST = path.join(SOURCE_ROOT, "loadtest", "demo", "dist");

let template: Template;
let json: any;

beforeAll(() => {
  // Hermetic: guarantee the gitignored webpack output dir exists so the demo
  // BucketDeployment asset can be staged during synth.
  fs.mkdirSync(DEMO_DIST, { recursive: true });
  const app = appWithCdkContext();
  const stack = new BidderSimulatorStack(app, "BiddingServerSimulator");
  template = Template.fromStack(stack);
  json = template.toJSON();
});

describe("BidderSimulatorStack — EnableRtbFabric parameter + HasRtbFabric condition", () => {
  it("defines EnableRtbFabric as String default 'true' with allowed values", () => {
    template.hasParameter("EnableRtbFabric", {
      Type: "String",
      Default: "true",
      AllowedValues: ["true", "false"],
    });
  });

  it("defines HasRtbFabric = (EnableRtbFabric == 'true')", () => {
    template.hasCondition("HasRtbFabric", {
      "Fn::Equals": [{ Ref: "EnableRtbFabric" }, "true"],
    });
  });

  it("does not accept/emit a build-time includeRtbFabric boolean", () => {
    expect(JSON.stringify(json)).not.toContain("includeRtbFabric");
  });
});

describe("BidderSimulatorStack — Responder Gateway gated by HasRtbFabric", () => {
  it("creates the Responder Gateway gated by HasRtbFabric", () => {
    template.resourceCountIs("AWS::RTBFabric::ResponderGateway", 1);
    const gws = template.findResources("AWS::RTBFabric::ResponderGateway");
    expect((Object.values(gws)[0] as any).Condition).toBe("HasRtbFabric");
  });

  it("gates the ALB ingress rule from the Responder GW (standalone CfnSecurityGroupIngress)", () => {
    const ingresses = template.findResources("AWS::EC2::SecurityGroupIngress");
    const entries = Object.values(ingresses);
    expect(entries.length).toBe(1);
    expect((entries[0] as any).Condition).toBe("HasRtbFabric");
    expect((entries[0] as any).Properties.FromPort).toBe(80);
  });

  it("gates the ResponderGatewayId / ResponderGatewayArn outputs by HasRtbFabric", () => {
    const idOut = Object.entries(json.Outputs as Record<string, any>).find(([id]) => id.includes("ResponderGatewayId"));
    const arnOut = Object.entries(json.Outputs as Record<string, any>).find(([id]) => id.includes("ResponderGatewayArn"));
    expect(idOut![1].Condition).toBe("HasRtbFabric");
    expect(arnOut![1].Condition).toBe("HasRtbFabric");
  });

  it("pins ResponderGatewayId to the flat logical id read by deploy.sh (exact key)", () => {
    // deploy.sh: RESPONDER_GW_ID=$(get_stack_output "$SIMULATOR_STACK_NAME" "ResponderGatewayId")
    // then passed to simulator-fabric-link.sh --responder-gateway-id. The output is conditional
    // (HasRtbFabric) but the logical id must be the flat "ResponderGatewayId".
    template.hasOutput("ResponderGatewayId", {
      Description: "RTB Fabric Responder Gateway ID",
      Condition: "HasRtbFabric",
    });
    expect(Object.keys(template.findOutputs("ResponderGatewayId")).length).toBe(1);
  });

  it("emits the unconditional VPC-peering outputs consumed by deploy.sh with flat (exact) logical ids", () => {
    // deploy.sh reads each of these by EXACT key on the vpc-peering path; they must be flat.
    for (const key of [
      "BidderSimulatorVpcId",
      "BidderSimulatorAlbSecurityGroupId",
      "BidderSimulatorRouteTableId1",
      "BidderSimulatorRouteTableId2",
      "BidderSimulatorAlbEndpoint",
    ]) {
      expect(Object.keys(template.findOutputs(key)).length).toBe(1);
      template.hasOutput(key, { Condition: Match.absent() });
    }
  });
});

describe("BidderSimulatorStack — demo BucketDeployment prune parity (task 9.4)", () => {
  // Mainline bidder_simulator_stack.py sets prune=False on both demo
  // BucketDeployments (DemoWebsiteDeployment + DemoAssetsDeployment) so that
  // neither deletes files uploaded by the other targeting the same bucket. The
  // CDK BucketDeployment `prune: false` synthesizes to Prune=false on the
  // Custom::CDKBucketDeployment custom resource.
  it("creates two demo BucketDeployment custom resources, both with Prune=false", () => {
    const deployments = template.findResources("Custom::CDKBucketDeployment");
    const entries = Object.values(deployments) as any[];
    expect(entries.length).toBe(2);
    for (const entry of entries) {
      expect(entry.Properties.Prune).toBe(false);
    }
  });

  // Task 9.6: Mainline sets memory_limit=512 (and no ephemeral storage) on BOTH
  // demo BucketDeployments. V2 was reconciled from 2048 MiB + 2 GiB ephemeral to
  // 512 MiB so both custom resources share the single 512 MiB CDK bucket-deployment
  // handler Lambda, matching Mainline exactly. Assert the shared handler is 512 MiB
  // with no enlarged ephemeral storage, and that neither demo custom resource uses
  // the 2048 MiB handler stem.
  it("uses a single 512 MiB bucket-deployment handler with no enlarged ephemeral storage", () => {
    const handlers = template.findResources("AWS::Lambda::Function");
    const bucketDeploymentHandlers = Object.entries(handlers).filter(([id]) =>
      id.startsWith("CustomCDKBucketDeployment"),
    ) as Array<[string, any]>;
    // Both demo deployments at 512 MiB collapse to a single shared handler.
    expect(bucketDeploymentHandlers.length).toBe(1);
    const [, handler] = bucketDeploymentHandlers[0];
    expect(handler.Properties.MemorySize).toBe(512);
    expect(handler.Properties.EphemeralStorage).toBeUndefined();
  });

  it("both demo BucketDeployment custom resources use the 512 MiB handler stem", () => {
    const deployments = template.findResources("Custom::CDKBucketDeployment");
    for (const id of Object.keys(deployments)) {
      expect(id).toContain("512MiB");
      expect(id).not.toContain("2048MiB");
    }
  });
});

describe("BidderSimulatorStack — VPC shape (coverage port from test_bidder_simulator_vpc.py, gap G1)", () => {
  // Ports the dead Python test_bidder_simulator_vpc.py assertions: the simulator
  // VPC is a single 10.1.0.0/16 VPC (DNS on) with 2 public + 2 private subnets
  // across 2 AZs and 2 NAT gateways. The 10.1.0.0/16 CIDR must NOT overlap the
  // PBS VPC CIDR (10.8.0.0/16) — the non-overlap invariant that lets the two VPCs
  // peer. There is no TS equivalent for these VPC assertions.
  it("creates exactly one VPC with CIDR 10.1.0.0/16 and DNS hostnames + support enabled", () => {
    template.resourceCountIs("AWS::EC2::VPC", 1);
    template.hasResourceProperties("AWS::EC2::VPC", {
      CidrBlock: "10.1.0.0/16",
      EnableDnsHostnames: true,
      EnableDnsSupport: true,
    });
  });

  it("creates 2 public + 2 private subnets (4 total across 2 AZs)", () => {
    template.resourceCountIs("AWS::EC2::Subnet", 4);
    const publicSubnets = template.findResources("AWS::EC2::Subnet", {
      Properties: { MapPublicIpOnLaunch: true },
    });
    expect(Object.keys(publicSubnets).length).toBe(2);
    const privateSubnets = template.findResources("AWS::EC2::Subnet", {
      Properties: { MapPublicIpOnLaunch: false },
    });
    expect(Object.keys(privateSubnets).length).toBe(2);
  });

  it("creates 2 NAT gateways (one per AZ for high availability)", () => {
    template.resourceCountIs("AWS::EC2::NatGateway", 2);
  });

  it("uses a CIDR (10.1.0.0/16) that does not overlap the PBS VPC CIDR (10.8.0.0/16)", () => {
    // Non-overlap invariant (Python test_vpc_cidr_non_overlapping_with_pbs):
    // assert the BSS VPC CIDR value, and that its second octet differs from PBS's.
    template.hasResourceProperties("AWS::EC2::VPC", { CidrBlock: "10.1.0.0/16" });
    const bidderCidr = "10.1.0.0/16";
    const pbsCidr = "10.8.0.0/16";
    expect(bidderCidr).not.toBe(pbsCidr);
    expect(Number(bidderCidr.split(".")[1])).not.toBe(Number(pbsCidr.split(".")[1]));
  });
});

describe("BidderSimulatorStack — internal ALB + Lambda target group (coverage port from test_bidder_simulator_alb.py, gap G2)", () => {
  // Ports the dead Python test_bidder_simulator_alb.py assertions: a single
  // internal application ALB, its security group description, a Lambda target
  // group with the exact health-check block, and an HTTP:80 listener. No TS
  // equivalent existed for the ALB/target-group/listener shape.
  it("creates exactly one internal application load balancer", () => {
    template.resourceCountIs("AWS::ElasticLoadBalancingV2::LoadBalancer", 1);
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
      Scheme: "internal",
      Type: "application",
    });
  });

  it("creates the ALB security group with the internal-ALB description", () => {
    template.hasResourceProperties("AWS::EC2::SecurityGroup", {
      GroupDescription: "Security group for internal bidder simulator ALB",
    });
  });

  it("creates a single Lambda target group with the configured health check", () => {
    template.resourceCountIs("AWS::ElasticLoadBalancingV2::TargetGroup", 1);
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::TargetGroup", {
      TargetType: "lambda",
      HealthCheckEnabled: true,
      HealthCheckPath: "/",
      HealthCheckIntervalSeconds: 30,
      HealthCheckTimeoutSeconds: 5,
      HealthyThresholdCount: 2,
      UnhealthyThresholdCount: 2,
    });
  });

  it("creates one HTTP listener on port 80", () => {
    template.resourceCountIs("AWS::ElasticLoadBalancingV2::Listener", 1);
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::Listener", {
      Port: 80,
      Protocol: "HTTP",
    });
  });
});

describe("BidderSimulatorStack — stack-level Metadata parity with Mainline (stays metadata-free)", () => {
  // Mainline's BidderSimulatorStack has NO template-level Metadata on either
  // branch. BSS extends the plain aws-cdk-lib Stack (not SolutionStack), so the
  // aws:solutions:* stamping added to the SolutionStack base must NOT leak here,
  // and BSS declares no StackParams so it gets no CloudFormation Interface block.
  it("emits no aws:solutions:* metadata and no CloudFormation Interface block", () => {
    const metadata = (json.Metadata ?? {}) as Record<string, unknown>;
    expect(metadata["aws:solutions:templatename"]).toBeUndefined();
    expect(metadata["aws:solutions:solution_id"]).toBeUndefined();
    expect(metadata["aws:solutions:solution_version"]).toBeUndefined();
    expect(metadata["AWS::CloudFormation::Interface"]).toBeUndefined();
  });
});
