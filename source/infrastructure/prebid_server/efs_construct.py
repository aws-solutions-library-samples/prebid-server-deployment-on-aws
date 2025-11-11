# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from aws_cdk import RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_efs as efs
from constructs import Construct

import prebid_server.stack_constants as stack_constants


class EfsConstruct(Construct):
    def __init__(
            self,
            scope,
            id,
            prebid_vpc,
    ) -> None:
        """
        This construct creates EFS resources.
        """
        super().__init__(scope, id)

        # Define EFS file system
        efs_security_group = ec2.SecurityGroup(self, "EfsSecurityGroup", vpc=prebid_vpc, allow_all_outbound=False)
        efs_security_group.node.default_child.add_metadata(
            "guard", {
                'SuppressedRules': ['SECURITY_GROUP_MISSING_EGRESS_RULE']
            }
        )

        self.prebid_fs = efs.FileSystem(
            self,
            "Prebid-fs",
            vpc=prebid_vpc,
            security_group=efs_security_group,
            performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
            lifecycle_policy=efs.LifecyclePolicy.AFTER_7_DAYS,
            vpc_subnets=ec2.SubnetSelection(subnet_group_name=stack_constants.PVT_SUBNET_NAME),
            removal_policy=RemovalPolicy.DESTROY,
            encrypted=True,
        )

        self.prebid_fs_access_point = efs.AccessPoint(
            self,
            "Prebid-fs-access-point",
            file_system=self.prebid_fs,
            path="/logging",
            create_acl=efs.Acl(owner_uid="1001", owner_gid="1001", permissions="770"),
            posix_user=efs.PosixUser(uid="1001", gid="1001"),
        )
