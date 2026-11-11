// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { Aws, CfnOutput, CfnParameter, CustomResource, Duration, RemovalPolicy } from "aws-cdk-lib";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import { DockerImageAsset, Platform } from "aws-cdk-lib/aws-ecr-assets";
import { Construct } from "constructs";
import { PowertoolsLayer, CrHelperLayer, pythonAssetCode } from "../shared/lambda-helpers";
import * as constants from "../shared/stack-constants";
import * as fs from "fs";
import * as path from "path";

/**
 * Base-image selection contract shared with the deployment/ecr build tooling.
 *
 * The closed set of supported bases, the default base, and the base -> Dockerfile
 * mapping are sourced from docker-build-config.json (keys SUPPORTED_BASES,
 * DEFAULT_BASE, BASE_DOCKERFILES) inside the docker build location so the CDK
 * image asset and the build script resolve Dockerfile.<base> identically
 * (Requirements 3.1, 3.2, 3.4, 3.5; design FR3.2/FR3.3). Values below are the
 * fallback used when the config file or a key is absent (e.g. a local synth
 * before the build step copies docker-build-config.json into place).
 */
const DEFAULT_BASE_FALLBACK = "al2023";
const SUPPORTED_BASES_FALLBACK = ["al2023", "alpine"];
const BASE_DOCKERFILES_FALLBACK: Record<string, string> = {
  al2023: "Dockerfile.al2023",
  alpine: "Dockerfile.alpine",
};

interface BaseSelectionConfig {
  defaultBase: string;
  supportedBases: string[];
  baseDockerfiles: Record<string, string>;
}

/**
 * Reads the base-image selection contract from docker-build-config.json in the
 * docker build location, falling back to the built-in defaults when the file or
 * individual keys are missing. This keeps the resolution contract in a single
 * source of truth (docker-build-config.json) shared with deployment/ecr/build-image.sh.
 */
function readBaseSelectionConfig(dockerBuildLocation: string): BaseSelectionConfig {
  const configPath = path.join(dockerBuildLocation, "docker-build-config.json");
  let parsed: Record<string, unknown> = {};
  try {
    if (fs.existsSync(configPath)) {
      parsed = JSON.parse(fs.readFileSync(configPath, "utf-8"));
    }
  } catch {
    // Malformed config falls back to the built-in contract below.
    parsed = {};
  }

  const defaultBase =
    typeof parsed.DEFAULT_BASE === "string" ? (parsed.DEFAULT_BASE as string) : DEFAULT_BASE_FALLBACK;
  const supportedBases = Array.isArray(parsed.SUPPORTED_BASES)
    ? (parsed.SUPPORTED_BASES as string[])
    : SUPPORTED_BASES_FALLBACK;
  const baseDockerfiles =
    parsed.BASE_DOCKERFILES && typeof parsed.BASE_DOCKERFILES === "object"
      ? (parsed.BASE_DOCKERFILES as Record<string, string>)
      : BASE_DOCKERFILES_FALLBACK;

  return { defaultBase, supportedBases, baseDockerfiles };
}

/**
 * Resolves the Docker build context (Dockerfiles + prebid config dirs) for the
 * image asset. Some build pipelines copy the `deployment/ecr/prebid-server` tree
 * into PKG_ROOT/docker as a separate packaging step. For a plain local
 * `cdk synth` that copy has not happened, so fall back to the original source at
 * `deployment/ecr/prebid-server` (two levels up from source/infrastructure).
 */
function resolveDockerBuildLocation(): string {
  const candidates = [
    path.join(constants.PKG_ROOT, "docker"),
    path.join(constants.PKG_ROOT, "..", "..", "deployment", "ecr", "prebid-server"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return candidates[0];
}

/**
 * Resolves the CDK image-asset Dockerfile name for the selected base, applying the
 * default-when-unset contract and validating against the closed set before returning
 * (Requirements 3.4, 3.5; design FR3.3). Throws a descriptive error naming the invalid
 * value on an unsupported base.
 */
export function resolveDockerfile(baseImage: string | undefined, dockerBuildLocation: string): string {
  const { defaultBase, supportedBases, baseDockerfiles } = readBaseSelectionConfig(dockerBuildLocation);
  const resolvedBase = baseImage && baseImage.length > 0 ? baseImage : defaultBase;

  if (!supportedBases.includes(resolvedBase)) {
    throw new Error(
      `Unsupported base image: '${resolvedBase}'. Supported values: ${supportedBases.join(", ")}.`,
    );
  }

  const dockerfile = baseDockerfiles[resolvedBase];
  if (!dockerfile) {
    throw new Error(
      `No Dockerfile mapping for base '${resolvedBase}' in docker-build-config.json (BASE_DOCKERFILES).`,
    );
  }
  return dockerfile;
}

export class ContainerImageConstruct extends Construct {
  public readonly imageEcsObj: ecs.ContainerImage;
  public readonly imageEcsStr: string;
  public readonly dockerConfigsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, storedRequestsBucket: s3.IBucket, deployBiddingSimulator = false) {
    super(scope, id);

    const dockerBuildLocation = resolveDockerBuildLocation();

    // Config upload — creates bucket + Lambda that uploads prebid configs to S3
    const configsManager = new PrebidConfigsManager(this, "ConfigFiles", dockerBuildLocation, storedRequestsBucket);
    this.dockerConfigsBucket = configsManager.dockerConfigBucket;

    const ecrRegistry = process.env.OVERRIDE_ECR_REGISTRY || process.env.PUBLIC_ECR_REGISTRY;

    if (!ecrRegistry) {
      // Resolve the base -> Dockerfile using the selection contract in
      // docker-build-config.json. When no baseImage context is supplied the
      // contract defaults to al2023 (design FR3.3); an unsupported value throws
      // an error naming the invalid value (Req 3.5).
      const baseImage = scope.node.tryGetContext("baseImage") as string | undefined;
      const dockerfile = resolveDockerfile(baseImage, dockerBuildLocation);
      const asset = new DockerImageAsset(this, "prebid-server", {
        directory: dockerBuildLocation,
        file: dockerfile,
        platform: Platform.LINUX_AMD64,
        buildArgs: { INCLUDE_AMT_BIDDER: deployBiddingSimulator ? "true" : "false" },
      });
      this.imageEcsObj = ecs.ContainerImage.fromDockerImageAsset(asset);
      this.imageEcsStr = asset.imageUri;
    } else {
      const imageParam = new CfnParameter(this, "ContainerImage", {
        type: "String",
        description: "The fully qualified name of the Prebid Server container image to deploy.",
        default: ecrRegistry,
      });
      this.imageEcsObj = ecs.ContainerImage.fromRegistry(imageParam.valueAsString);
      this.imageEcsStr = imageParam.valueAsString;
    }

    new CfnOutput(this, "PrebidECSImage", { value: this.imageEcsStr, description: "Prebid Server ECR Image" });
    new CfnOutput(this, "PrebidSolutionConfigBucket", {
      value: `https://${Aws.REGION}.console.aws.amazon.com/s3/home?region=${Aws.REGION}&bucket=${this.dockerConfigsBucket.bucketName}`,
      description: "Prebid Solution Configuration Bucket",
    });
  }
}

/**
 * Manages prebid config files: creates an S3 bucket and a Lambda custom resource
 * that uploads default-config, stored_requests, stored_responses, etc. to S3.
 * Ported from prebid_configs_construct.py.
 */
export class PrebidConfigsManager extends Construct {
  public readonly dockerConfigBucket: s3.Bucket;

  constructor(scope: Construct, id: string, dockerBuildLocation: string, storedRequestsBucket: s3.IBucket) {
    super(scope, id);

    this.dockerConfigBucket = new s3.Bucket(this, "Bucket", {
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER,
      accessControl: s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      versioned: true,
      autoDeleteObjects: false,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    (this.dockerConfigBucket.node.findChild("Resource") as s3.CfnBucket).addMetadata("guard", {
      SuppressedRules: ["S3_BUCKET_LOGGING_ENABLED"],
    });

    const role = new iam.Role(this, "UploadRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      inlinePolicies: {
        LambdaCrLoggingPolicy: new iam.PolicyDocument({
          statements: [new iam.PolicyStatement({
            actions: ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
            resources: [`arn:${Aws.PARTITION}:logs:${Aws.REGION}:${Aws.ACCOUNT_ID}:log-group:/aws/lambda/*`],
          })],
        }),
        LambdaDockerConfigS3Policy: new iam.PolicyDocument({
          statements: [new iam.PolicyStatement({
            actions: ["s3:DeleteObject", "s3:GetObject", "s3:PutObject", "s3:ListBucket"],
            resources: [
              this.dockerConfigBucket.bucketArn, `${this.dockerConfigBucket.bucketArn}/*`,
              storedRequestsBucket.bucketArn, `${storedRequestsBucket.bucketArn}/*`,
            ],
            conditions: { StringEquals: { "aws:ResourceAccount": [Aws.ACCOUNT_ID] } },
          })],
        }),
      },
    });
    (role.node.defaultChild as iam.CfnRole).addMetadata("guard", { SuppressedRules: ["IAM_NO_INLINE_POLICY_CHECK"] });

    // If the stored requests bucket uses KMS encryption, grant the role access to the key
    if (storedRequestsBucket.encryptionKey) {
      storedRequestsBucket.encryptionKey.grantEncryptDecrypt(role);
    }

    const uploadFn = new lambda.Function(this, "UploadFunction", {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "upload_prebid_configs.event_handler",
      code: pythonAssetCode(path.join(constants.CUSTOM_RESOURCES_PATH, "prebid_configs_lambda")),
      role,
      description: "Lambda to upload prebid configs to S3",
      memorySize: 256,
      timeout: Duration.minutes(1),
      architecture: lambda.Architecture.ARM_64,
      layers: [PowertoolsLayer.getOrCreate(this), CrHelperLayer.getOrCreate(this)],
      environment: {
        SOLUTION_ID: this.node.tryGetContext("SOLUTION_ID") ?? "",
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
      },
    });
    (uploadFn.node.findChild("Resource") as lambda.CfnFunction).addMetadata("guard", {
      SuppressedRules: ["LAMBDA_INSIDE_VPC", "LAMBDA_CONCURRENCY_CHECK"],
    });

    new CustomResource(this, "UploadDockerConfigsCr", {
      serviceToken: uploadFn.functionArn,
      // Bound how long CloudFormation waits on this custom resource. Without it, a
      // stuck custom-resource Lambda leaves the stack waiting on the default ~1h
      // timeout, which stalls deployments and rollbacks. This is just a config
      // upload, so a 5-minute ceiling is ample.
      serviceTimeout: Duration.minutes(5),
      properties: {
        docker_configs_bucket_name: this.dockerConfigBucket.bucketName,
        stored_requests_bucket_name: storedRequestsBucket.bucketName,
        SOLUTION_VERSION: this.node.tryGetContext("SOLUTION_VERSION") ?? "",
      },
    });
  }
}
