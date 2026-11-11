// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the ECS task-definition vCPU/memory mechanical property change
// (task 7.5: `stack-constants.ts` VCPU 1024 -> 2048, feeding
// `ecs-task-construct.ts` FargateTaskDefinition.cpu).
//
// Scope (Stage 2a verification notes, task 7.5, "Applied — stack_constants.py"):
// Mainline bumped the container vCPU to 2048 (2 vCPU). `VCPU` drives
// `FargateTaskDefinition.cpu`; memory (`MEMORY_LIMIT_MIB`) stays 4096. Both entry
// deployments (ALB + CloudFront) instantiate an EcsTaskConstruct, so the stack
// synthesizes two ECS TaskDefinitions, each Cpu="2048" / Memory="4096".
//
// The cfn-parameter-migration suite (7.9) asserts the TaskDefinition Environment
// (AMT_ADAPTER_ENABLED / AMT_BIDDING_SERVER_SIMULATOR_ENDPOINT /
// LOG_ANALYTICS_ENABLED Fn::If chains) but does NOT assert Cpu/Memory, so these
// property assertions do not duplicate it.

import { Template } from "aws-cdk-lib/assertions";
import { PrebidServerStack } from "../../../lib/prebid_server/prebid-server-stack";
import { VCPU, MEMORY_LIMIT_MIB } from "../../../lib/shared/stack-constants";
import { appWithCdkContext } from "../../test-helpers";

let template: Template;

beforeAll(() => {
  const app = appWithCdkContext();
  const stack = new PrebidServerStack(app, PrebidServerStack.STACK_NAME);
  template = Template.fromStack(stack);
});

describe("EcsTaskConstruct — task-definition vCPU/memory (task 7.5)", () => {
  it("VCPU constant is 2048 (2 vCPU) and memory is 4096", () => {
    expect(VCPU).toBe(2048);
    expect(MEMORY_LIMIT_MIB).toBe(4096);
  });

  it("synthesizes two Fargate task definitions (one per entry deployment)", () => {
    template.resourceCountIs("AWS::ECS::TaskDefinition", 2);
  });

  it("every task definition emits Cpu='2048' and Memory='4096'", () => {
    const taskDefs = template.findResources("AWS::ECS::TaskDefinition");
    const entries = Object.entries(taskDefs);
    expect(entries).toHaveLength(2);
    for (const [, td] of entries) {
      expect(td.Properties.Cpu).toBe("2048");
      expect(td.Properties.Memory).toBe("4096");
    }
  });

  it("task definitions are Fargate/awsvpc with Cpu='2048' Memory='4096' (hasResourceProperties)", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", {
      Cpu: "2048",
      Memory: "4096",
      RequiresCompatibilities: ["FARGATE"],
      NetworkMode: "awsvpc",
    });
  });
});
