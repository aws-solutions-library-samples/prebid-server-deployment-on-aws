// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { CfnMapping, Stack } from "aws-cdk-lib";
import { Construct } from "constructs";

/**
 * SolutionStack base class for AWS Solutions compatibility.
 * Provides description formatting, solution metadata mappings,
 * and SourceCode mapping for the Solutions publishing pipeline.
 */
export class SolutionStack extends Stack {
  public readonly solutionId: string;
  public readonly solutionVersion: string;

  constructor(scope: Construct, id: string, props: {
    description: string;
    templateFilename: string;
    [key: string]: any;
  }) {
    const solutionId = scope.node.tryGetContext("SOLUTION_ID") ?? "SO0248";
    const solutionVersion = scope.node.tryGetContext("SOLUTION_VERSION") ?? "v2.0.0";
    const solutionName = scope.node.tryGetContext("SOLUTION_NAME") ?? "Guidance for Deploying a Prebid Server on AWS";
    const bucketName = scope.node.tryGetContext("BUCKET_NAME") ?? "BUCKET_NAME";

    super(scope, id, {
      ...props,
      description: `(${solutionId}) - ${props.description}. Version ${solutionVersion}`,
    });

    this.solutionId = solutionId;
    this.solutionVersion = solutionVersion;

    // Stamp the AWS Solutions template-level metadata tags, mirroring the
    // Mainline `TemplateOptions._get_metadata()` mechanism
    // (cdk_solution_helper_py/helpers_cdk/aws_solutions/cdk/interfaces.py).
    // These are merged with (not clobbered by) the CloudFormation Interface
    // metadata that StackParams.registerParameterGroups adds later — the base
    // constructor runs first via super(), so StackParams reads and extends
    // this object rather than replacing it.
    //
    // Stamped here (in the base, only extended by PrebidServerStack) so that
    // BidderSimulatorStack — which extends the plain aws-cdk-lib Stack, not
    // SolutionStack — remains metadata-free, matching its Mainline counterpart.
    const existingMetadata = (this.templateOptions.metadata =
      this.templateOptions.metadata ?? {}) as Record<string, unknown>;
    existingMetadata["aws:solutions:templatename"] = props.templateFilename;
    existingMetadata["aws:solutions:solution_id"] = solutionId;
    existingMetadata["aws:solutions:solution_version"] = solutionVersion;

    // Solution metadata mapping — used by operational metrics and CloudWatch metrics Lambdas
    new CfnMapping(this, "Solution", {
      mapping: {
        Data: {
          ID: solutionId,
          Version: solutionVersion,
          SendAnonymizedData: "Yes",
        },
      },
    });

    // SourceCode mapping — used by the Solutions publishing pipeline for S3 asset references
    new CfnMapping(this, "SourceCode", {
      mapping: {
        General: {
          S3Bucket: bucketName,
          KeyPrefix: `${solutionName}/${solutionVersion}`,
        },
      },
    });
  }
}
