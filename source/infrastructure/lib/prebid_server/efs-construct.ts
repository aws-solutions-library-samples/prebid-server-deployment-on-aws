// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { RemovalPolicy } from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as efs from "aws-cdk-lib/aws-efs";
import { Construct } from "constructs";
import * as constants from "../shared/stack-constants";

export class EfsConstruct extends Construct {
  public readonly prebidFs: efs.FileSystem;
  public readonly prebidFsAccessPoint: efs.AccessPoint;

  constructor(scope: Construct, id: string, prebidVpc: ec2.IVpc) {
    super(scope, id);

    const efsSg = new ec2.SecurityGroup(this, "EfsSecurityGroup", {
      vpc: prebidVpc,
      allowAllOutbound: false,
    });
    (efsSg.node.defaultChild as ec2.CfnSecurityGroup).addMetadata("guard", {
      SuppressedRules: ["SECURITY_GROUP_MISSING_EGRESS_RULE"],
    });

    this.prebidFs = new efs.FileSystem(this, "Prebid-fs", {
      vpc: prebidVpc,
      securityGroup: efsSg,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_7_DAYS,
      vpcSubnets: { subnetGroupName: constants.PVT_SUBNET_NAME },
      removalPolicy: RemovalPolicy.DESTROY,
      encrypted: true,
    });

    this.prebidFsAccessPoint = new efs.AccessPoint(this, "Prebid-fs-access-point", {
      fileSystem: this.prebidFs,
      path: "/logging",
      createAcl: { ownerUid: "1001", ownerGid: "1001", permissions: "770" },
      posixUser: { uid: "1001", gid: "1001" },
    });
  }
}
