// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { execFileSync } from "child_process";
import * as fs from "fs";
import * as path from "path";

import { AssetHashType, BundlingOptions, DockerImage, ILocalBundling, Stack } from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

import * as constants from "./stack-constants";

const POWERTOOLS_CONSTRUCT_ID = "PowertoolsLayer-8E932F0F";
const SOLUTIONS_LAYER_CONSTRUCT_ID = "SolutionsLayer-C36";
const CRHELPER_CONSTRUCT_ID = "CrHelperLayer-A4F1";

// Root of the AWS Solutions CDK python helper sources. Some build pipelines copy
// this directory into the package root (PKG_ROOT/cdk_solution_helper_py) and
// pre-populate its layer asset dirs as a separate step. For a plain local
// `cdk synth` neither has happened, so we resolve to whichever location exists -
// the copied-in build location first, then the original source tree one level up
// (source/cdk_solution_helper_py).
function resolveSolutionHelperRoot(): string {
  const candidates = [
    path.join(constants.PKG_ROOT, "cdk_solution_helper_py"),
    path.join(constants.PKG_ROOT, "..", "cdk_solution_helper_py"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  // Fall back to the build-location path; the bundler will surface a clear error.
  return candidates[0];
}

const SOLUTION_HELPER_ROOT = resolveSolutionHelperRoot();

/**
 * Returns true when a Lambda layer asset output already contains an installed
 * `python/` directory. Some build environments install Python dependencies as a
 * separate step before `cdk synth` runs and pre-populate the asset's `python/`
 * directory; in that case the layer is already complete and this bundler must NOT
 * run `pip` again (the build host may have no network access or no `pip` on PATH).
 */
function layerAlreadyPopulated(outputDir: string): boolean {
  const pythonTarget = path.join(outputDir, "python");
  return fs.existsSync(pythonTarget) && fs.readdirSync(pythonTarget).length > 0;
}

/**
 * Local (Docker-free) bundler for AWS Solutions Python Lambda layers: the layer's
 * source requirements directory is copied into the CDK asset output, then
 * dependencies are pip-installed into a `python/` subdirectory so the layer follows
 * the Lambda layer runtime layout. This keeps `cdk synth` self-contained on a
 * developer workstation.
 *
 * If the asset's `python/` directory is already populated (see
 * `layerAlreadyPopulated`), the `pip install` is skipped. This supports operators
 * who install layer dependencies as a separate build step and run `cdk synth` in an
 * environment without network access or `pip` on PATH.
 */
class SolutionsPythonLayerBundling implements ILocalBundling {
  constructor(
    private readonly sourceDir: string,
    private readonly libraryDirs: string[] = [],
  ) {}

  tryBundle(outputDir: string, _options: BundlingOptions): boolean {
    if (!fs.existsSync(this.sourceDir)) {
      throw new Error(
        `Powertools/Solutions layer source not found at ${this.sourceDir}. ` +
          `Expected the AWS Solutions CDK python helpers to be present.`,
      );
    }

    // Copy the source requirements directory into the asset output.
    fs.cpSync(this.sourceDir, outputDir, { recursive: true });

    // Copy any additional library directories alongside the requirements.
    for (const lib of this.libraryDirs) {
      fs.cpSync(lib, path.join(outputDir, path.basename(lib)), { recursive: true });
    }

    // If dependencies were installed by a separate build step (asset's python/ is
    // already populated), skip pip so this synthesizes in environments without
    // network access or pip on PATH.
    if (layerAlreadyPopulated(outputDir)) {
      return true;
    }

    const requirementsFile = path.join(outputDir, "requirements.txt");
    if (fs.existsSync(requirementsFile)) {
      const pythonTarget = path.join(outputDir, "python");
      fs.mkdirSync(pythonTarget, { recursive: true });
      execFileSync(
        "pip",
        ["install", "--quiet", "-t", pythonTarget, "-r", requirementsFile],
        { stdio: "inherit" },
      );
      // Lambda's Python runtime already provides boto3/botocore; drop them to keep
      // the layer small.
      for (const entry of fs.readdirSync(pythonTarget)) {
        if (entry.startsWith("boto3") || entry.startsWith("botocore")) {
          fs.rmSync(path.join(pythonTarget, entry), { recursive: true, force: true });
        }
      }
    }

    return true;
  }
}

/**
 * Local (Docker-free) bundler for a Python Lambda *function* asset. Copies the
 * function source directory into the CDK asset output; when `requirements.txt`
 * lists any third-party packages, pip-installs them into the asset root (NOT
 * a `python/` subdirectory - this is function code, not a layer).
 *
 * `requirements.txt` is the single source of truth for extra function-asset
 * deps, shared with any build step that pre-populates function directories.
 * Deps satisfied by attached layers should NOT be listed there.
 *
 * Deps may arrive one of two ways:
 *   1. A separate build step (used by internal build environments) pre-populated
 *      them into the function source dir from a package cache; cpSync brings them into
 *      the asset output, `allRequirementsPresent` sees them, and pip is skipped.
 *   2. Neither pre-populate happened; pip installs the declared packages into
 *      the asset root at synth time.
 */
class PythonFunctionBundling implements ILocalBundling {
  constructor(private readonly sourceDir: string) {}

  tryBundle(outputDir: string, _options: BundlingOptions): boolean {
    if (!fs.existsSync(this.sourceDir)) {
      throw new Error(`Python Lambda source not found at ${this.sourceDir}.`);
    }

    fs.cpSync(this.sourceDir, outputDir, { recursive: true });

    const requirements = readFunctionRequirements(this.sourceDir);
    if (requirements.length === 0) return true;
    if (allRequirementsPresent(outputDir, requirements)) return true;

    // Install from the requirements.txt file (already cpSync'd into outputDir
    // above) rather than passing package specs as CLI args — mirrors the
    // container-fallback path and lets pip natively handle comments/env markers.
    execFileSync(
      "pip",
      ["install", "--quiet", "-r", path.join(outputDir, "requirements.txt"), "-t", outputDir],
      { stdio: "inherit" },
    );
    return true;
  }
}

/**
 * Parse `requirements.txt` at the root of a function dir. Returns the distribution
 * names to install into the function asset, skipping blank/comment lines. Version
 * specifiers are preserved so `pip install` receives them intact.
 */
export function readFunctionRequirements(dir: string): string[] {
  const file = path.join(dir, "requirements.txt");
  if (!fs.existsSync(file)) return [];
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .map((l) => l.split("#")[0].trim())
    .filter((l) => l.length > 0);
}

/**
 * Returns true when every declared requirement has a corresponding installed
 * directory or `.dist-info`/`.egg-info` marker in `outputDir`. Package name
 * hyphens/underscores are normalized (PyPI naming is inconsistent), and version
 * specifiers are stripped for the presence check. Used to decide whether a
 * synth-time `pip install` is still needed after a separate build step has
 * cpSync'd the deps into the asset.
 */
function allRequirementsPresent(outputDir: string, requirements: string[]): boolean {
  const entries = new Set(fs.readdirSync(outputDir));
  return requirements.every((raw) => {
    const pkg = raw.split(/[<>=!~;\[ ]/)[0].trim();
    const dashName = pkg.replace(/_/g, "-");
    const underName = pkg.replace(/-/g, "_");
    if (entries.has(dashName) || entries.has(underName)) return true;
    return [...entries].some(
      (e) =>
        (e.startsWith(`${dashName}-`) || e.startsWith(`${underName}-`)) &&
        (e.endsWith(".dist-info") || e.endsWith(".egg-info")),
    );
  });
}

/**
 * Returns a bundled `lambda.Code` for a Python custom-resource Lambda directory.
 *
 * Extra function-asset deps are declared in `<dirPath>/requirements.txt` — the
 * single source of truth shared with any build step that pre-populates
 * function directories.
 * Deps satisfied by attached layers should NOT appear there; a Lambda whose
 * imports are fully covered by layers has no `requirements.txt` (or an empty
 * one) and this reduces to a plain cpSync at synth.
 *
 * Bundling always runs locally via `PythonFunctionBundling` (host `pip`, no
 * container). If pip is missing OR the install fails, the bundler throws and
 * synth aborts — this is intentional: the recovery path is "install pip, or
 * pre-populate the deps in a separate build step", not "silently start a Docker
 * daemon the developer didn't opt into". The `image` block below is the stub
 * CDK's bundling API requires; it is NOT reached in practice because the local
 * bundler never returns `false`.
 */
export function pythonAssetCode(dirPath: string): lambda.Code {
  const requirements = readFunctionRequirements(dirPath);
  return lambda.Code.fromAsset(dirPath, {
    assetHashType: AssetHashType.OUTPUT,
    bundling: {
      // Required by the CDK bundling API but not exercised at synth (see
      // docstring above). If we ever start returning `false` from
      // `PythonFunctionBundling.tryBundle`, this is the command CDK would run.
      image: lambda.Runtime.PYTHON_3_11.bundlingImage,
      command:
        requirements.length === 0
          ? ["bash", "-c", "cp -au . /asset-output"]
          : [
              "bash",
              "-c",
              "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
            ],
      local: new PythonFunctionBundling(dirPath),
    },
  });
}

function bundledLayerCode(sourceDir: string, libraryDirs: string[] = []): lambda.Code {
  return lambda.Code.fromAsset(sourceDir, {
    assetHashType: AssetHashType.OUTPUT,
    bundling: {
      // Docker image is required by the type but never used: all bundling is local.
      image: DockerImage.fromRegistry("scratch"),
      local: new SolutionsPythonLayerBundling(sourceDir, libraryDirs),
    },
  });
}

/**
 * Local (Docker-free) bundler for the Redis Lambda layer. Runs:
 *
 * ```
 * pip install redis cachetools --no-deps -t /asset-output/python && cp -ru . /asset-output/python/
 * ```
 *
 * Both `redis` AND `cachetools` are installed into a `python/` subdirectory (the
 * Lambda layer runtime layout) with `--no-deps` so the layer stays minimal. The
 * source dir's own files (`cache_access.py`, `requirements.txt`) are then copied
 * into `python/` too.
 *
 * A plain `lambda.Code.fromAsset(cache_lambda)` would ship the layer WITHOUT
 * `redis`/`cachetools` (the source dir has no pre-built `python/`), so the
 * CacheHandler would crash at invoke with
 * `Runtime.ImportModuleError: No module named 'redis'`, breaking the VAST cache
 * path (/openrtb2/video -> HTTP 500, instream video does not render).
 *
 * If the asset's `python/` directory is already populated (dependencies installed
 * by a separate build step), the `pip install` is skipped so this synthesizes in
 * environments without network access or `pip` on PATH.
 */
class RedisLayerBundling implements ILocalBundling {
  // Packages installed with --no-deps to keep the layer minimal.
  private static readonly PACKAGES = ["redis", "cachetools"];

  constructor(private readonly sourceDir: string) {}

  tryBundle(outputDir: string, _options: BundlingOptions): boolean {
    if (!fs.existsSync(this.sourceDir)) {
      throw new Error(`Redis layer source not found at ${this.sourceDir}.`);
    }

    // Copy the source dir (handler + requirements + any pre-populated python/)
    // into the asset output first, so the "already populated?" guard below can
    // see it. Mirrors the shape used by SolutionsPythonLayerBundling.
    fs.cpSync(this.sourceDir, outputDir, { recursive: true });

    // If dependencies were installed by a separate build step (asset's python/ is
    // already populated), skip pip so this synthesizes in environments without
    // network access or pip on PATH.
    if (layerAlreadyPopulated(outputDir)) {
      return true;
    }

    const pythonTarget = path.join(outputDir, "python");
    fs.mkdirSync(pythonTarget, { recursive: true });

    // pip install redis cachetools --no-deps -t <out>/python
    execFileSync(
      "pip",
      ["install", "--quiet", "--no-deps", "-t", pythonTarget, ...RedisLayerBundling.PACKAGES],
      { stdio: "inherit" },
    );

    // cp -ru . <out>/python/ - bring the handler source + requirements alongside
    // the installed packages.
    fs.cpSync(this.sourceDir, pythonTarget, { recursive: true });

    return true;
  }
}

/**
 * Returns a bundled `lambda.Code` for the Redis Lambda layer. Bundling always
 * runs locally via `RedisLayerBundling`; if pip is missing OR fails, synth
 * aborts (see `pythonAssetCode` docstring for the rationale). The `image`
 * block below is the stub CDK's bundling API requires; it is not exercised in
 * practice.
 */
export function redisLayerCode(sourceDir: string): lambda.Code {
  return lambda.Code.fromAsset(sourceDir, {
    assetHashType: AssetHashType.OUTPUT,
    bundling: {
      image: lambda.Runtime.PYTHON_3_11.bundlingImage,
      command: [
        "bash",
        "-c",
        "pip install redis cachetools --no-deps -t /asset-output/python && cp -ru . /asset-output/python/",
      ],
      local: new RedisLayerBundling(sourceDir),
    },
  });
}

/**
 * Lambda Layer providing aws_lambda_powertools. Dependencies are bundled
 * locally at synth time (pip install into python/), or consumed as-is when a
 * separate build step has pre-installed them.
 */
export class PowertoolsLayer {
  static getOrCreate(scope: Construct): lambda.ILayerVersion {
    const stack = Stack.of(scope);
    const existing = stack.node.tryFindChild(POWERTOOLS_CONSTRUCT_ID);
    if (existing) return existing as lambda.LayerVersion;

    return new lambda.LayerVersion(stack, POWERTOOLS_CONSTRUCT_ID, {
      code: bundledLayerCode(
        path.join(
          SOLUTION_HELPER_ROOT,
          "helpers_cdk/aws_solutions/cdk/aws_lambda/layers/aws_lambda_powertools/requirements",
        ),
      ),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: "AWS Lambda Powertools",
    });
  }
}

/**
 * Lambda Layer providing crhelper. Dependencies are bundled locally at synth
 * time (pip install into python/), or consumed as-is when a separate build
 * step has pre-installed them. Kept as a separate layer from PowertoolsLayer
 * so a Lambda that only uses crhelper (e.g. wait_for_gateway_lambda) doesn't
 * cold-start with the ~34 MB powertools bundle.
 */
export class CrHelperLayer {
  static getOrCreate(scope: Construct): lambda.ILayerVersion {
    const stack = Stack.of(scope);
    const existing = stack.node.tryFindChild(CRHELPER_CONSTRUCT_ID);
    if (existing) return existing as lambda.LayerVersion;

    return new lambda.LayerVersion(stack, CRHELPER_CONSTRUCT_ID, {
      code: bundledLayerCode(
        path.join(
          SOLUTION_HELPER_ROOT,
          "helpers_cdk/aws_solutions/cdk/aws_lambda/layers/crhelper/requirements",
        ),
      ),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: "crhelper for CloudFormation custom resources",
    });
  }
}

/**
 * Lambda Layer providing the aws_solutions.core helpers.
 * The aws_solutions package is copied into a python/ subdirectory at synth time.
 */
export class SolutionsLayer {
  static getOrCreate(scope: Construct): lambda.ILayerVersion {
    const stack = Stack.of(scope);
    const existing = stack.node.tryFindChild(SOLUTIONS_LAYER_CONSTRUCT_ID);
    if (existing) return existing as lambda.LayerVersion;

    return new lambda.LayerVersion(stack, SOLUTIONS_LAYER_CONSTRUCT_ID, {
      code: lambda.Code.fromAsset(path.join(SOLUTION_HELPER_ROOT, "helpers_common"), {
        assetHashType: AssetHashType.OUTPUT,
        bundling: {
          image: DockerImage.fromRegistry("scratch"),
          local: new SolutionsCommonLayerBundling(path.join(SOLUTION_HELPER_ROOT, "helpers_common")),
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: "AWS Solutions common helpers",
    });
  }
}

/**
 * Local bundler for the SolutionsLayer: copies the `aws_solutions` package into a
 * `python/` subdirectory so it is importable from a Lambda layer. If a separate
 * build step has already populated the asset's `python/` directory, the copy is
 * skipped so this synthesizes without re-doing the work.
 */
class SolutionsCommonLayerBundling implements ILocalBundling {
  constructor(private readonly sourceDir: string) {}

  tryBundle(outputDir: string, _options: BundlingOptions): boolean {
    // If the layer was pre-populated by a separate build step, use it as-is.
    if (layerAlreadyPopulated(outputDir)) {
      return true;
    }
    const awsSolutions = path.join(this.sourceDir, "aws_solutions");
    if (!fs.existsSync(awsSolutions)) {
      throw new Error(`Solutions layer source not found at ${awsSolutions}.`);
    }
    const pythonTarget = path.join(outputDir, "python", "aws_solutions");
    fs.mkdirSync(pythonTarget, { recursive: true });
    fs.cpSync(awsSolutions, pythonTarget, { recursive: true });
    return true;
  }
}
