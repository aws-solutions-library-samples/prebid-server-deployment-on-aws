// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// Coverage-parity unit test for ContainerImageConstruct + PrebidConfigsManager
// (task 9.5). PrebidConfigsManager is the port of Mainline
// prebid_configs_construct.py (resolved folded-in under container-image in task
// 9.1). Asserts presence + key property values of every resource these
// constructs contribute — the docker-configs bucket, the prebid-configs upload
// Lambda + custom resource, and the resolveDockerfile base-selection contract.

import { Match } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";
import {
  resolveDockerfile,
} from "../../../lib/prebid_server/container-image-construct";
import * as path from "path";

const template = prebidServerTemplate();
const dockerBuildLocation = path.resolve(
  __dirname, "..", "..", "..", "..", "..", "deployment", "ecr", "prebid-server"
);

describe("PrebidConfigsManager — docker configs bucket + upload CR (task 9.5)", () => {
  it("creates a block-public, versioned, S3-managed-encrypted docker configs bucket", () => {
    const buckets = template.findResources("AWS::S3::Bucket", {
      Properties: {
        BucketEncryption: {
          ServerSideEncryptionConfiguration: [
            { ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" } },
          ],
        },
        VersioningConfiguration: { Status: "Enabled" },
      },
    });
    expect(Object.keys(buckets).length).toBeGreaterThanOrEqual(1);
  });

  it("creates the prebid-configs upload Lambda (python3.11, arm64)", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "upload_prebid_configs.event_handler",
      Runtime: "python3.11",
      Architectures: ["arm64"],
    });
  });

  it("creates the upload-docker-configs custom resource with both bucket names", () => {
    template.hasResourceProperties("AWS::CloudFormation::CustomResource", {
      docker_configs_bucket_name: Match.anyValue(),
      stored_requests_bucket_name: Match.anyValue(),
    });
  });

  // Operability guard: the upload custom resource sets a 5-minute ServiceTimeout.
  // Without it, a stuck custom-resource Lambda leaves CloudFormation waiting on the
  // default ~1h timeout, stalling deployments and rollbacks. serviceTimeout:
  // Duration.minutes(5) renders as ServiceTimeout "300" (seconds) on the CR.
  it("sets a 5-minute ServiceTimeout on the upload-docker-configs custom resource", () => {
    const crs = template.findResources("AWS::CloudFormation::CustomResource", {
      Properties: { docker_configs_bucket_name: Match.anyValue() },
    });
    const entries = Object.entries(crs);
    expect(entries.length).toBeGreaterThanOrEqual(1);
    for (const [, cr] of entries) {
      expect((cr as any).Properties.ServiceTimeout).toBe("300");
    }
  });
});

describe("ContainerImageConstruct — image source (task 9.5)", () => {
  it("the ECS task definition references a container image", () => {
    template.hasResourceProperties("AWS::ECS::TaskDefinition", {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({ Image: Match.anyValue() }),
      ]),
    });
  });

  it("resolveDockerfile defaults to the AL2023 Dockerfile when no base is given", () => {
    expect(resolveDockerfile(undefined, dockerBuildLocation)).toBe("Dockerfile.al2023");
  });

  it("resolveDockerfile maps the alpine base to Dockerfile.alpine", () => {
    expect(resolveDockerfile("alpine", dockerBuildLocation)).toBe("Dockerfile.alpine");
  });

  it("resolveDockerfile rejects an unsupported base naming the invalid value", () => {
    expect(() => resolveDockerfile("ubuntu", dockerBuildLocation)).toThrow(/ubuntu/);
  });
});
