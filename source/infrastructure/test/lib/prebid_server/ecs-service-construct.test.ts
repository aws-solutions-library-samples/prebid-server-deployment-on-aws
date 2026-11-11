// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the ALB -> ECS port 8443 security group rule (task 7.3,
// `ecs-service-construct.ts`, wired from both entry deployments).
//
// Scope (Stage 2a verification notes, task 7.3): the ECS/Fargate service
// security group must permit ingress from the public Prebid-ALB security group
// on the HTTPS container port (8443). The rule is emitted by
// `fargateService.connections.allowFrom(albSecGroup, ec2.Port.tcp(CONTAINER_PORT), ...)`
// guarded by the `albSecGroup` prop, which both the ALB and CloudFront entry
// deployments wire in. There is one entry path each, so the synthesized template
// carries exactly two port-8443 ingress rules.
//
// These assertions cover presence (resourceCountIs on the 8443 subset) and the
// property values of every field the construct contributes to the rule:
// GroupId -> Fargate service SG, SourceSecurityGroupId -> Prebid-ALB SG,
// IpProtocol=tcp, FromPort=ToPort=8443, and the matching description. They do
// not overlap the cfn-parameter-migration suite (7.9), which asserts the
// UseVpcPeering-gated bidder ingress rule, not the 8443 ALB->ECS rule.

import { Match, Template } from "aws-cdk-lib/assertions";
import { PrebidServerStack } from "../../../lib/prebid_server/prebid-server-stack";
import { CONTAINER_PORT } from "../../../lib/shared/stack-constants";
import { appWithCdkContext } from "../../test-helpers";

let template: Template;

beforeAll(() => {
  const app = appWithCdkContext();
  const stack = new PrebidServerStack(app, PrebidServerStack.STACK_NAME);
  template = Template.fromStack(stack);
});

/** Return only the SecurityGroupIngress resources on the 8443 container port. */
function ingressOn8443(): Array<[string, any]> {
  const all = template.findResources("AWS::EC2::SecurityGroupIngress");
  return Object.entries(all).filter(
    ([, r]) => (r as any).Properties?.FromPort === CONTAINER_PORT
  );
}

describe("EcsServiceConstruct — ALB->ECS port 8443 SG rule (task 7.3)", () => {
  it("uses 8443 as the HTTPS container port constant", () => {
    expect(CONTAINER_PORT).toBe(8443);
  });

  it("emits exactly two port-8443 ingress rules (one per entry deployment)", () => {
    expect(ingressOn8443()).toHaveLength(2);
  });

  it("each 8443 rule is tcp, FromPort=ToPort=8443, with the ALB->containers description", () => {
    const rules = ingressOn8443();
    expect(rules).toHaveLength(2);
    for (const [, rule] of rules) {
      expect(rule.Properties.IpProtocol).toBe("tcp");
      expect(rule.Properties.FromPort).toBe(8443);
      expect(rule.Properties.ToPort).toBe(8443);
      expect(rule.Properties.Description).toBe(
        "Allow ALB to reach containers on HTTPS port"
      );
    }
  });

  it("each 8443 rule targets a Fargate service SG (GroupId) sourced from a Prebid-ALB SG", () => {
    const rules = ingressOn8443();
    expect(rules).toHaveLength(2);
    for (const [, rule] of rules) {
      // GroupId -> the ECS/Fargate service security group.
      const groupIdRef = rule.Properties.GroupId["Fn::GetAtt"];
      expect(groupIdRef).toBeDefined();
      expect(groupIdRef[1]).toBe("GroupId");
      expect(groupIdRef[0]).toMatch(/FargateServiceSecurityGroup/);

      // SourceSecurityGroupId -> the public Prebid-ALB security group.
      const sourceRef = rule.Properties.SourceSecurityGroupId["Fn::GetAtt"];
      expect(sourceRef).toBeDefined();
      expect(sourceRef[1]).toBe("GroupId");
      expect(sourceRef[0]).toMatch(/PrebidALBsecuritygroup/);
    }
  });

  it("emits the 8443 rule for the ALB entry path (hasResourceProperties)", () => {
    template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", {
      IpProtocol: "tcp",
      FromPort: 8443,
      ToPort: 8443,
      Description: "Allow ALB to reach containers on HTTPS port",
      GroupId: {
        "Fn::GetAtt": [
          Match.stringLikeRegexp("ALBEntryDeployment.*FargateServiceSecurityGroup.*"),
          "GroupId",
        ],
      },
      SourceSecurityGroupId: {
        "Fn::GetAtt": [
          Match.stringLikeRegexp("ALBEntryDeploymentPrebidALBsecuritygroup.*"),
          "GroupId",
        ],
      },
    });
  });

  it("emits the 8443 rule for the CloudFront entry path (hasResourceProperties)", () => {
    template.hasResourceProperties("AWS::EC2::SecurityGroupIngress", {
      IpProtocol: "tcp",
      FromPort: 8443,
      ToPort: 8443,
      Description: "Allow ALB to reach containers on HTTPS port",
      GroupId: {
        "Fn::GetAtt": [
          Match.stringLikeRegexp("CloudFrontEntryDeployment.*FargateServiceSecurityGroup.*"),
          "GroupId",
        ],
      },
      SourceSecurityGroupId: {
        "Fn::GetAtt": [
          Match.stringLikeRegexp("CloudFrontEntryDeploymentPrebidALBsecuritygroup.*"),
          "GroupId",
        ],
      },
    });
  });
});
