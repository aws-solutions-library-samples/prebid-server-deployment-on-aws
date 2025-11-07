# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import jsii
import aws_cdk
from aws_cdk import CfnCondition, CfnResource, CfnOutput
from constructs import Construct, IConstruct


@jsii.implements(aws_cdk.IAspect)
class ConditionAspect(Construct):
    def __init__(self, scope: Construct, id: str, condition: CfnCondition):
        super().__init__(scope, id)

        self.condition = condition

    def visit(self, node: IConstruct) -> None:
        if isinstance(node, CfnResource) and node.cfn_options:
            node.cfn_options.condition = self.condition
        if isinstance(node, CfnOutput):
            node.condition = self.condition
