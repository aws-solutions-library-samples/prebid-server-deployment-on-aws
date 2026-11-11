// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { IAspect, CfnResource, CfnOutput, CfnCondition } from "aws-cdk-lib";
import { IConstruct } from "constructs";

/**
 * CDK Aspect that applies a CloudFormation condition to all CfnResource and CfnOutput nodes.
 */
export class ConditionAspect implements IAspect {
  constructor(private readonly condition: CfnCondition) {}

  public visit(node: IConstruct): void {
    if (node instanceof CfnResource) {
      node.cfnOptions.condition = this.condition;
    }
    if (node instanceof CfnOutput) {
      node.condition = this.condition;
    }
  }
}
