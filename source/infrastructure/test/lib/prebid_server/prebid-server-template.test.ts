// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test mirroring Mainline test_prebid_server_template.py
// (task 9.5): full-stack synth assertions for the top-level PrebidServerStack
// resources — the ECS cluster (container insights), the ECS services + task
// definitions, the ALB listeners + target groups, the stored-requests bucket +
// access-logs bucket, and the stack-level header-secret custom resource. Also
// validates the stack synthesizes without cross-stack Fn::ImportValue references.

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("PrebidServerStack template — top-level resources (task 9.5)", () => {
  it("creates exactly one ECS cluster with container insights enabled", () => {
    template.resourceCountIs("AWS::ECS::Cluster", 1);
    template.hasResourceProperties("AWS::ECS::Cluster", {
      ClusterSettings: Match.arrayWith([
        { Name: "containerInsights", Value: "enabled" },
      ]),
    });
  });

  it("creates two ECS services and two Fargate task definitions (one per entry deployment)", () => {
    template.resourceCountIs("AWS::ECS::Service", 2);
    template.resourceCountIs("AWS::ECS::TaskDefinition", 2);
  });

  it("creates ALB listeners and target groups", () => {
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::Listener", {
      Protocol: Match.anyValue(),
    });
    expect(
      Object.keys(template.findResources("AWS::ElasticLoadBalancingV2::TargetGroup")).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("creates an internet-facing public ALB (coverage port from test_prebid_server_template.py, gap G4)", () => {
    // Ports the dead Python test_prebid_server_template.py public-ALB assertion.
    // The PBS stack synthesizes BOTH a public ALB (Scheme=internet-facing,
    // created by the ALB + CloudFront entry deployments) AND internal ALBs
    // (Scheme=internal, from the ECS service construct). Target the internet-facing
    // one specifically via hasResourceProperties so the internal ones don't mask it.
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
      Scheme: "internet-facing",
      Type: "application",
    });
  });

  it("creates the header-secret-gen Lambda + custom resource", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "header_secret_gen.event_handler",
      Runtime: "python3.11",
    });
  });

  it("creates the stored-requests bucket and its access-logs bucket (server access logging)", () => {
    const buckets = template.findResources("AWS::S3::Bucket");
    const storedReqAccessLogs = Object.keys(buckets).filter((k) =>
      k.startsWith("StoredRequestsAccessLogsBucket")
    );
    expect(storedReqAccessLogs.length).toBe(1);
    // The stored-requests bucket logs to the access-logs bucket.
    template.hasResourceProperties("AWS::S3::Bucket", {
      LoggingConfiguration: Match.objectLike({
        LogFilePrefix: "stored-requests-bucket-logs/",
      }),
    });
  });

  it("synthesizes with no cross-stack Fn::ImportValue references", () => {
    const json = JSON.stringify(template.toJSON());
    expect(json).not.toContain("Fn::ImportValue");
  });

  it("applies IAM roles and SolutionsLayer/PowertoolsLayer Lambda layers", () => {
    expect(
      Object.keys(template.findResources("AWS::IAM::Role")).length
    ).toBeGreaterThanOrEqual(1);
    // Layers: PowertoolsLayer, CrHelperLayer, SolutionsLayer, RedisLayer, and the
    // name-only operational-metrics layer.
    template.resourceCountIs("AWS::Lambda::LayerVersion", 6);
  });
});

describe("PrebidServerStack template — CloudFormation Outputs parity with Mainline", () => {
  // These 4 outputs are exposed by Mainline's synthesized PSS template but were
  // omitted from the V2 TypeScript CDK. Each is ported into the V2 construct
  // that owns the underlying resource, matching Mainline's key, value,
  // description, and CfnCondition exactly.

  it("exposes PrebidStoredRequestsBucket (S3 console URL, no condition)", () => {
    template.hasOutput("PrebidStoredRequestsBucket", {
      Description: "Bucket for Prebid Server stored requests",
      Value: {
        "Fn::Join": [
          "",
          [
            "https://",
            { Ref: "AWS::Region" },
            ".console.aws.amazon.com/s3/home?region=",
            { Ref: "AWS::Region" },
            "&bucket=",
            { Ref: "Bucket83908E77" },
          ],
        ],
      },
    });
  });

  it("exposes PrebidWAFWebACL (GetAtt webacl_name) gated by DeployCloudFrontWafCondition", () => {
    template.hasOutput("PrebidWAFWebACL", {
      Description: "Prebid WAF WebACL",
      Value: {
        "Fn::GetAtt": [
          "CloudFrontEntryDeploymentCloudFrontWafWafWebAclCrFCDE9D36",
          "webacl_name",
        ],
      },
      Condition: "DeployCloudFrontWafCondition",
    });
  });

  it("exposes the ALB-path EFS id (Mainline's 'systemd' typo preserved) gated by DeployALBHttpsCondition", () => {
    // Logical id carries a construct-path prefix + hash
    // (ALBEntryDeploymentPrebidEFSId...), so match on any output ("*").
    template.hasOutput("*", {
      Description: "EFS file systemd id",
      Value: { Ref: "ALBEntryDeploymentEfsPrebidfs53F94271" },
      Condition: "DeployALBHttpsCondition",
    });
  });

  it("exposes the CloudFront-path EFS id gated by DeployCloudFrontWafCondition", () => {
    template.hasOutput("*", {
      Description: "Prebid EFS Id",
      Value: { Ref: "CloudFrontEntryDeploymentEfsPrebidfs0F9DEEFD" },
      Condition: "DeployCloudFrontWafCondition",
    });
  });
});

describe("PrebidServerStack template — pinned output logical IDs (script contract + Mainline key= parity)", () => {
  // Regression guard: a live us-east-1 V2 deploy succeeded but the post-deploy
  // deployment/simulator_fabric_link.py failed with
  //   "RequesterGatewayId not found in stack outputs"
  // because these CfnOutputs were created inside nested constructs WITHOUT an
  // overrideLogicalId, so CDK emitted path-prefixed, hash-suffixed logical IDs
  // (e.g. RtbFabricRequesterGatewayId19EAE8CB). Mainline pinned each of these
  // with CfnOutput(..., key="<exact>"), and simulator_fabric_link.py / deploy.sh
  // read them by EXACT key. These assertions lock the flat logical IDs in place.
  //
  // helper: findOutputs returns { <logicalId>: { ... } } for an exact id.
  const outputExists = (logicalId: string) =>
    Object.keys(template.findOutputs(logicalId)).length === 1;

  it("EcsClusterName — read by simulator_fabric_link.py (outputs.get('EcsClusterName'))", () => {
    expect(outputExists("EcsClusterName")).toBe(true);
    template.hasOutput("EcsClusterName", { Description: "ECS Cluster Name" });
  });

  it("EcsServiceName — read by simulator_fabric_link.py (outputs.get('EcsServiceName'))", () => {
    expect(outputExists("EcsServiceName")).toBe(true);
    template.hasOutput("EcsServiceName", { Description: "ECS Service Name" });
  });

  it("RequesterGatewayId — read by simulator_fabric_link.py (outputs.get('RequesterGatewayId'))", () => {
    expect(outputExists("RequesterGatewayId")).toBe(true);
    template.hasOutput("RequesterGatewayId", {
      Description: "RTB Fabric Requester Gateway ID",
      Condition: "HasRtbRequesterGateway",
    });
  });

  it("RequesterGatewayArn — Mainline key= parity (conditional output)", () => {
    expect(outputExists("RequesterGatewayArn")).toBe(true);
    template.hasOutput("RequesterGatewayArn", {
      Description: "RTB Fabric Requester Gateway ARN",
      Condition: "HasRtbRequesterGateway",
    });
  });

  it("PrebidALBDNSName — Mainline key= parity (flat, no hyphen), gated by DeployALBHttpsCondition", () => {
    expect(outputExists("PrebidALBDNSName")).toBe(true);
    template.hasOutput("PrebidALBDNSName", {
      Description: "Prebid ALB DNS Name",
      Condition: "DeployALBHttpsCondition",
    });
  });

  it("PrebidCloudFrontDistributionEndpoint — Mainline key= parity, gated by DeployCloudFrontWafCondition", () => {
    expect(outputExists("PrebidCloudFrontDistributionEndpoint")).toBe(true);
    template.hasOutput("PrebidCloudFrontDistributionEndpoint", {
      Description: "Prebid CloudFront Distribution Endpoint",
      Condition: "DeployCloudFrontWafCondition",
    });
  });

  it("PrebidWAFWebACL — Mainline key= parity, gated by DeployCloudFrontWafCondition", () => {
    expect(outputExists("PrebidWAFWebACL")).toBe(true);
    template.hasOutput("PrebidWAFWebACL", {
      Description: "Prebid WAF WebACL",
      Condition: "DeployCloudFrontWafCondition",
    });
  });

  it("VpcPeeringConnectionId — Mainline key= parity (conditional on UseVpcPeering)", () => {
    expect(outputExists("VpcPeeringConnectionId")).toBe(true);
    template.hasOutput("VpcPeeringConnectionId", {
      Description: "VPC Peering Connection ID between Prebid Server and Bidder Simulator VPCs",
      Condition: "UseVpcPeering",
    });
  });

  it("none of the pinned keys leak a path-prefixed / hash-suffixed variant", () => {
    const allOutputIds = Object.keys(template.toJSON().Outputs ?? {});
    for (const key of [
      "EcsClusterName",
      "EcsServiceName",
      "RequesterGatewayId",
      "RequesterGatewayArn",
      "PrebidALBDNSName",
      "PrebidCloudFrontDistributionEndpoint",
      "PrebidWAFWebACL",
      "VpcPeeringConnectionId",
    ]) {
      const matches = allOutputIds.filter((id) => id.includes(key));
      // Exactly one output id contains the key, and it equals the key (flat).
      expect(matches).toEqual([key]);
    }
  });
});

describe("PrebidServerStack template — stack-level Metadata parity with Mainline", () => {
  // Mainline's SolutionStack base (interfaces.py TemplateOptions._get_metadata)
  // stamps three aws:solutions:* tags plus a CloudFormation Interface block
  // carrying BOTH ParameterGroups and ParameterLabels. The Parity_Verifier only
  // diffs Resources, so these top-level Metadata keys were missed. V2 previously
  // emitted only Interface.ParameterGroups. These assertions lock in the full
  // set: the 3 aws:solutions:* keys stamped in the SolutionStack base and the
  // ParameterLabels merged (not clobbered) alongside ParameterGroups by
  // StackParams.

  // The 14 deploy-time parameters declared by StackParams. BootstrapVersion (the
  // synthetic CDK bootstrap parameter) is intentionally excluded — it carries no
  // ParameterLabels entry on either branch.
  const EXPECTED_PARAMETER_LABELS = [
    "InstallCloudFrontAndWAF",
    "SSLCertificateARN",
    "ECSTaskMinCapacity",
    "ECSTaskMaxCapacity",
    "RequestsPerTargetThreshold",
    "SpotInstanceWeight",
    "ContainerImageUri",
    "EnableLogAnalytics",
    "EnableRtbRequesterGateway",
    "SimulatorVpcId",
    "SimulatorAlbSgId",
    "SimulatorRouteTableId1",
    "SimulatorRouteTableId2",
    "SimulatorEndpoint",
  ];

  it("stamps the three aws:solutions:* metadata keys (templatename, solution_id, solution_version)", () => {
    const metadata = template.toJSON().Metadata ?? {};
    expect(metadata["aws:solutions:templatename"]).toBe("prebid-server-deployment-on-aws.template");
    // solution_id/version come from cdk.json context (SO0248 / v2.0.0) via the
    // SolutionStack base. Assert presence + the fixed id; the version is
    // branch-specific by design so only its presence is asserted.
    expect(metadata["aws:solutions:solution_id"]).toBe("SO0248");
    expect(metadata["aws:solutions:solution_version"]).toBeDefined();
  });

  it("emits AWS::CloudFormation::Interface with BOTH ParameterGroups and ParameterLabels (merge not clobber)", () => {
    const metadata = template.toJSON().Metadata ?? {};
    const iface = metadata["AWS::CloudFormation::Interface"] ?? {};
    expect(iface.ParameterGroups).toBeDefined();
    expect(Array.isArray(iface.ParameterGroups)).toBe(true);
    expect(iface.ParameterLabels).toBeDefined();
  });

  it("emits one ParameterLabels entry per declared parameter with default == logical id", () => {
    const metadata = template.toJSON().Metadata ?? {};
    const labels = metadata["AWS::CloudFormation::Interface"].ParameterLabels as Record<
      string,
      { default: string }
    >;
    expect(Object.keys(labels).sort()).toEqual([...EXPECTED_PARAMETER_LABELS].sort());
    for (const logicalId of EXPECTED_PARAMETER_LABELS) {
      expect(labels[logicalId]).toEqual({ default: logicalId });
    }
  });
});
