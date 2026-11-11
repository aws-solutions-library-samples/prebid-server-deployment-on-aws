// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for EfsConstruct (task 9.5).
// TypeScript-only construct coverage (Req 6.3): asserts presence + key property
// values of every resource EfsConstruct contributes. EfsConstruct is
// instantiated once per entry deployment (ALB + CloudFront), so the stack
// synthesizes 2 file systems, 2 access points, and their mount targets.

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

const template = prebidServerTemplate();

describe("EfsConstruct — encrypted EFS + access point (task 9.5)", () => {
  it("creates two encrypted EFS file systems (one per entry deployment)", () => {
    template.resourceCountIs("AWS::EFS::FileSystem", 2);
    template.hasResourceProperties("AWS::EFS::FileSystem", {
      Encrypted: true,
      PerformanceMode: "generalPurpose",
      LifecyclePolicies: [{ TransitionToIA: "AFTER_7_DAYS" }],
    });
  });

  it("creates an access point at /logging with posix uid/gid 1001 and 770 perms", () => {
    template.resourceCountIs("AWS::EFS::AccessPoint", 2);
    template.hasResourceProperties("AWS::EFS::AccessPoint", {
      PosixUser: { Uid: "1001", Gid: "1001" },
      RootDirectory: {
        Path: "/logging",
        CreationInfo: { OwnerUid: "1001", OwnerGid: "1001", Permissions: "770" },
      },
    });
  });

  it("provisions mount targets across the private subnets (2 AZs x 2 deployments)", () => {
    template.resourceCountIs("AWS::EFS::MountTarget", 4);
  });

  it("the EFS file-system policy requires access via mount target", () => {
    template.hasResourceProperties("AWS::EFS::FileSystem", {
      FileSystemPolicy: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Condition: { Bool: { "elasticfilesystem:AccessedViaMountTarget": "true" } },
          }),
        ]),
      }),
    });
  });
});
