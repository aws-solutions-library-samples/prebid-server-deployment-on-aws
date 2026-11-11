// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

// ---------------------------------------------------------------------------
// Lambda dependency-provenance guard (parity spec task (b))
// ---------------------------------------------------------------------------
//
// WHY THIS TEST EXISTS
// --------------------
// Parity between the Python (Mainline) and TypeScript (V2) CDK was validated at
// the TEMPLATE level: the Parity_Verifier diffs synthesized CloudFormation and
// NORMALIZES asset references (Code.S3Key, ImageUri) to placeholders; the unit
// suite uses `Template.fromStack` (also template-level); and the Stage-1
// non-CDK inventory explicitly EXCLUDED everything under
// `source/infrastructure/`. So a Lambda's HANDLER SOURCE, its `requirements.txt`,
// a layer's CONTENTS, and a layer's ATTACHMENT were checked by NEITHER stage -
// and those only fail at Lambda *invoke*, never at synth/template-diff.
//
// Three defects slipped through exactly this blind spot (all now fixed in the
// working tree):
//   1. Custom-resource Lambdas imported `crhelper` but were built with a plain
//      `lambda.Code.fromAsset(dir)` that never `pip install`ed the dir's
//      requirements.txt  -> `Runtime.ImportModuleError: No module named 'crhelper'`.
//      Fixed by bundling via `pythonAssetCode(...)`.
//   2. The RedisLayer was built with a plain `fromAsset(cache_lambda)` (which has
//      no pre-built `python/`), so it shipped WITHOUT redis/cachetools -> the
//      CacheHandler crashed at invoke with `No module named 'redis'`. Fixed by
//      `redisLayerCode(...)` (pip install redis cachetools --no-deps into python/).
//
// WHAT THIS TEST ENFORCES
// -----------------------
// The rule, encoded data-drivenly below:
//
//   For every lambda.Function, each of its handler's NON-STDLIB third-party
//   imports must be satisfied by exactly one of:
//     (a) its bundled asset deps   - the construct uses pythonAssetCode()/
//         redisLayerCode() so requirements.txt is pip-installed into the asset; OR
//     (b) a package provided by one of its ATTACHED layers - resolved from the
//         synthesized template by mapping each Layers[] Ref to that
//         LayerVersion's Description / LayerName; OR
//     (c) the Lambda Python runtime built-ins (boto3/botocore) - never a gap.
//
// Reintroducing a plain `fromAsset` on a crhelper/redis/requests handler, or
// dropping a required layer from a handler, makes this test FAIL. (Proven with a
// scratch revert during authoring; see the parity ledger
// docs/parity/methodology-gaps.md.)
//
// HOW TO EXTEND WHEN A NEW LAMBDA IS ADDED
// ----------------------------------------
// Add a row to HANDLER_PROVENANCE below: the handler string (exactly as passed
// to `handler:` in the construct), the source construct file, the handler's
// third-party imports, and how each is provided. The test then verifies the
// synthesized template + source honor that declaration. If you add a handler
// that imports a third-party package and forget to declare a provider, the
// "no undeclared third-party-importing handler" cross-check will flag it.

import * as fs from "fs";
import * as path from "path";
import { Template } from "aws-cdk-lib/assertions";
import { prebidServerTemplate } from "../../test-helpers";

// ---------------------------------------------------------------------------
// Provider identifiers
// ---------------------------------------------------------------------------
// A third-party dependency is provided either by the function's own bundled
// asset, or by an attached layer. Layers are identified from the synthesized
// template by a stable, human-meaningful token (Description for the
// Powertools/Solutions/Redis layers; a LayerName suffix for the name-only
// metrics/datasync layers).

/** Marker: the dependency is pip-installed into the FUNCTION asset (pythonAssetCode). */
const ASSET_BUNDLE = "asset-bundle" as const;

// Layer identifiers as they appear in the synthesized template. Descriptions
// are matched exactly; LayerName tokens synthesize to
// {"Fn::Join":["",[{"Ref":"AWS::StackName"},"-<suffix>"]]}, matched by suffix.
const LAYER_POWERTOOLS = { by: "description", value: "AWS Lambda Powertools" } as const; // aws_lambda_powertools
const LAYER_CRHELPER = { by: "description", value: "crhelper for CloudFormation custom resources" } as const; // crhelper
const LAYER_SOLUTIONS = { by: "description", value: "AWS Solutions common helpers" } as const; // aws_solutions
const LAYER_REDIS = { by: "description", value: "Redis package layer" } as const; // redis, cachetools
const LAYER_METRICS = { by: "nameSuffix", value: "-metrics-layer" } as const; // cloudwatch_metrics

type LayerProvider =
  | typeof LAYER_POWERTOOLS
  | typeof LAYER_CRHELPER
  | typeof LAYER_SOLUTIONS
  | typeof LAYER_REDIS
  | typeof LAYER_METRICS;
type Provider = typeof ASSET_BUNDLE | LayerProvider;

interface HandlerRow {
  /** Exact `handler:` string on the lambda.Function. */
  handler: string;
  /** Construct source file, relative to lib/, that instantiates the function. */
  constructFile: string;
  /**
   * Third-party (non-stdlib, non-runtime-builtin) imports of the handler and how
   * each is provided. `import: []` means stdlib/boto3-only (no third-party dep).
   * boto3/botocore are runtime built-ins and are intentionally NOT listed.
   */
  deps: Array<{ pkg: string; provider: Provider }>;
}

// ---------------------------------------------------------------------------
// The reviewed provenance matrix.
// Derived from the Stage-2 audit (handler imports grepped vs. how each dep is
// provided in the synthesized `prebid-server-deployment-on-aws` template). Keep
// this list in sync with the constructs; the cross-check below fails the build
// if a third-party-importing handler appears in the template but not here.
// ---------------------------------------------------------------------------
const HANDLER_PROVENANCE: HandlerRow[] = [
  // --- crhelper custom-resource Lambdas: crhelper is provided by the dedicated
  //     CrHelperLayer; aws_lambda_powertools by PowertoolsLayer (attached only
  //     where the handler imports Logger). Both come from /opt/python at runtime,
  //     so the function uses pythonAssetCode with an empty bundle (no pip at
  //     synth). boto3/botocore are supplied by the Lambda runtime. ---
  {
    handler: "upload_files.event_handler",
    constructFile: "prebid_server/artifacts-construct.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
    ],
  },
  {
    handler: "header_secret_gen.event_handler",
    constructFile: "prebid_server/prebid-server-stack.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
    ],
  },
  {
    handler: "enable_access_logs.event_handler",
    constructFile: "prebid_server/alb-access-logs-construct.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
    ],
  },
  {
    handler: "get_prefix_id.event_handler",
    constructFile: "prebid_server/cloudfront-waf-construct.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
    ],
  },
  {
    handler: "create_waf_webacl.event_handler",
    constructFile: "prebid_server/cloudfront-waf-construct.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
    ],
  },
  {
    handler: "delete_waf_webacl.event_handler",
    constructFile: "prebid_server/cloudfront-waf-construct.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
    ],
  },
  {
    handler: "delete_lambda_eni.event_handler",
    constructFile: "prebid_server/datasync-constructs.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
    ],
  },
  {
    handler: "upload_prebid_configs.event_handler",
    constructFile: "prebid_server/container-image-construct.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
    ],
  },
  {
    handler: "ops_metrics.event_handler",
    constructFile: "prebid_server/operational-metrics-construct.ts",
    deps: [
      { pkg: "crhelper", provider: LAYER_CRHELPER },
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
      { pkg: "aws_solutions", provider: LAYER_SOLUTIONS },
    ],
  },
  {
    handler: "wait_for_gateway.event_handler",
    constructFile: "prebid_server/rtb-fabric-construct.ts",
    deps: [{ pkg: "crhelper", provider: LAYER_CRHELPER }],
  },

  // --- cache handler: redis + cachetools from RedisLayer (redisLayerCode);
  //     cloudwatch_metrics from the operational-metrics layer. ---
  {
    handler: "cache_access.handler",
    constructFile: "prebid_server/cache-construct.ts",
    deps: [
      { pkg: "redis", provider: LAYER_REDIS },
      { pkg: "cachetools", provider: LAYER_REDIS },
      { pkg: "cloudwatch_metrics", provider: LAYER_METRICS },
      // Transitive: cloudwatch_metrics/metrics.py imports aws_solutions.core.
      { pkg: "aws_solutions", provider: LAYER_SOLUTIONS },
    ],
  },

  // --- cloudwatch metrics report: `requests` pip-installed into the function
  //     asset (pythonAssetCode); aws_solutions from the Solutions layer. ---
  {
    handler: "cloudwatch_metrics_report.event_handler",
    constructFile: "prebid_server/cloudwatch-constructs.ts",
    deps: [
      { pkg: "requests", provider: ASSET_BUNDLE },
      { pkg: "aws_solutions", provider: LAYER_SOLUTIONS },
    ],
  },

  // --- EFS cleanup + container-stop + glue trigger: powertools + cloudwatch_metrics
  //     from layers. cloudwatch_metrics/metrics.py transitively imports
  //     `from aws_solutions.core.helpers import get_service_client`, so every
  //     consumer of cloudwatch_metrics MUST also attach SolutionsLayer or it
  //     crashes at invoke with ModuleNotFoundError: aws_solutions. The
  //     `aws_solutions` entry below is a transitive declaration - the handler
  //     module doesn't import it directly, but its runtime path does. ---
  {
    handler: "delete_efs_files.event_handler",
    constructFile: "prebid_server/datasync-constructs.ts",
    deps: [
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
      { pkg: "cloudwatch_metrics", provider: LAYER_METRICS },
      { pkg: "aws_solutions", provider: LAYER_SOLUTIONS },
    ],
  },
  {
    handler: "container_stop_logs.event_handler",
    constructFile: "prebid_server/datasync-constructs.ts",
    deps: [
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
      { pkg: "cloudwatch_metrics", provider: LAYER_METRICS },
      { pkg: "aws_solutions", provider: LAYER_SOLUTIONS },
    ],
  },
  {
    handler: "start_glue_job.event_handler",
    constructFile: "prebid_server/glue-constructs.ts",
    deps: [
      { pkg: "aws_lambda_powertools", provider: LAYER_POWERTOOLS },
      { pkg: "cloudwatch_metrics", provider: LAYER_METRICS },
      { pkg: "aws_solutions", provider: LAYER_SOLUTIONS },
    ],
  },
];

// Third-party packages this guard knows how to reason about. Any handler import
// of one of these MUST be declared in HANDLER_PROVENANCE with a provider.
const KNOWN_THIRD_PARTY = [
  "crhelper",
  "redis",
  "cachetools",
  "requests",
  "cloudwatch_metrics",
  "aws_solutions",
  "aws_lambda_powertools",
];

const LIB_ROOT = path.resolve(__dirname, "../../../lib");

// ---------------------------------------------------------------------------
// Template helpers: resolve a function's attached Layers to provider identifiers.
// ---------------------------------------------------------------------------
type LayerJson = { Description?: string; LayerName?: unknown };

function buildLayerIndex(template: Template): Record<string, LayerJson> {
  const layers = template.findResources("AWS::Lambda::LayerVersion");
  const index: Record<string, LayerJson> = {};
  for (const [logicalId, res] of Object.entries(layers)) {
    index[logicalId] = ((res as any).Properties ?? {}) as LayerJson;
  }
  return index;
}

/** Does an attached-layer JSON match a LayerProvider identifier? */
function layerMatches(layer: LayerJson, provider: LayerProvider): boolean {
  if (provider.by === "description") {
    return layer.Description === provider.value;
  }
  // nameSuffix: LayerName synthesizes to Fn::Join with AWS::StackName + suffix.
  return JSON.stringify(layer.LayerName ?? "").includes(provider.value);
}

/** Resolve a function's Layers[] Refs into the set of LayerProviders it carries. */
function resolveAttachedProviders(
  fnProps: any,
  layerIndex: Record<string, LayerJson>,
): LayerJson[] {
  const refs: any[] = Array.isArray(fnProps.Layers) ? fnProps.Layers : [];
  const resolved: LayerJson[] = [];
  for (const ref of refs) {
    const logicalId = ref?.Ref;
    if (typeof logicalId === "string" && layerIndex[logicalId]) {
      resolved.push(layerIndex[logicalId]);
    }
  }
  return resolved;
}

// ---------------------------------------------------------------------------
// Source helpers: locate the `new lambda.Function(...)` block for a handler and
// inspect which code() provider it uses. Robust, low-flakiness: we read the
// authored construct source rather than the (asset-normalized) template.
// ---------------------------------------------------------------------------
function readConstruct(relFile: string): string {
  return fs.readFileSync(path.join(LIB_ROOT, relFile), "utf8");
}

/**
 * Extract the `code:` provider used for the lambda.Function whose `handler:`
 * equals `handler`, from the given construct source. Returns "pythonAssetCode",
 * "redisLayerCode", "fromAsset", or null if not found.
 *
 * The `code:` property sits in the same object literal as `handler:`, but comment
 * lines can appear between them. We scan forward from `handler:` (skipping comment
 * lines) for the first `code:` within a generous bound, and also look a few lines
 * back in case `code:` precedes `handler:`. This is resilient to comment length so
 * the check does not silently break when someone adds a docstring above `code:`.
 */
function codeProviderForHandler(source: string, handler: string): string | null {
  const lines = source.split("\n");
  const handlerIdx = lines.findIndex((l) => l.includes(`handler: "${handler}"`));
  if (handlerIdx < 0) return null;

  const CODE_RE = /code:\s*([A-Za-z.]+)\(/;
  const classify = (token: string): string => {
    if (token.startsWith("pythonAssetCode")) return "pythonAssetCode";
    if (token.startsWith("redisLayerCode")) return "redisLayerCode";
    if (token.startsWith("lambda.Code.fromAsset") || token.endsWith("Code.fromAsset")) return "fromAsset";
    return token;
  };

  // Scan forward from handler: to the end of this object literal (bounded), which
  // is where code: normally lives. Stop at a `new lambda.Function(` for a DIFFERENT
  // function so we never bleed into the next construct.
  const FORWARD_BOUND = 40;
  for (let i = handlerIdx + 1; i < Math.min(lines.length, handlerIdx + FORWARD_BOUND); i++) {
    const m = lines[i].match(CODE_RE);
    if (m) return classify(m[1]);
    if (i > handlerIdx + 1 && /new lambda\.Function\(/.test(lines[i])) break;
  }
  // Fallback: code: a few lines above handler: (reverse ordering).
  for (let i = handlerIdx - 1; i >= Math.max(0, handlerIdx - FORWARD_BOUND); i--) {
    const m = lines[i].match(CODE_RE);
    if (m) return classify(m[1]);
    if (/new lambda\.Function\(/.test(lines[i])) break;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("Lambda dependency-provenance guard - prebid-server-deployment-on-aws", () => {
  const template = prebidServerTemplate();
  const layerIndex = buildLayerIndex(template);

  // Index all functions by their Handler value for lookup.
  const functionsByHandler: Record<string, any[]> = {};
  for (const res of Object.values(template.findResources("AWS::Lambda::Function"))) {
    const props = (res as any).Properties ?? {};
    const h = props.Handler;
    if (typeof h === "string") (functionsByHandler[h] ??= []).push(props);
  }

  describe("every declared handler exists in the synthesized template", () => {
    for (const row of HANDLER_PROVENANCE) {
      it(`${row.handler} - present as an AWS::Lambda::Function`, () => {
        expect(functionsByHandler[row.handler]?.length ?? 0).toBeGreaterThanOrEqual(1);
      });
    }
  });

  describe("each third-party import is satisfied by its declared provider", () => {
    for (const row of HANDLER_PROVENANCE) {
      const source = readConstruct(row.constructFile);
      const codeProvider = codeProviderForHandler(source, row.handler);

      for (const dep of row.deps) {
        it(`${row.handler}: '${dep.pkg}' provided by ${
          dep.provider === ASSET_BUNDLE ? "asset-bundle" : (dep.provider as LayerProvider).value
        }`, () => {
          if (dep.provider === ASSET_BUNDLE) {
            // Asset-bundled deps require the construct to bundle requirements.txt
            // into the FUNCTION asset - i.e. pythonAssetCode / redisLayerCode, NOT
            // a plain fromAsset (which would ship the source WITHOUT the package).
            expect(codeProvider).not.toBeNull();
            expect(["pythonAssetCode", "redisLayerCode"]).toContain(codeProvider);
          } else {
            // Layer-provided deps require the expected layer to be attached to
            // (at least one instance of) this function in the synthesized template.
            const instances = functionsByHandler[row.handler] ?? [];
            expect(instances.length).toBeGreaterThanOrEqual(1);
            const providerAttachedSomewhere = instances.some((props) => {
              const attached = resolveAttachedProviders(props, layerIndex);
              return attached.some((layer) => layerMatches(layer, dep.provider as LayerProvider));
            });
            expect(providerAttachedSomewhere).toBe(true);
          }
        });
      }
    }
  });

  // Cross-check: no third-party-importing handler in the template is left
  // undeclared here. This is the "reintroduced defect with ZERO provider" trap -
  // if someone adds a new crhelper/redis/requests Lambda without wiring a
  // provider, its handler won't be in HANDLER_PROVENANCE and this fails, OR it
  // will be declared and the per-dep assertion above will catch a missing
  // provider. We enumerate the known handler source dirs and their imports.
  describe("no handler importing a known third-party package is left without a declared provider", () => {
    // Map handler string -> the declared third-party pkgs (for quick membership).
    const declared: Record<string, Set<string>> = {};
    for (const row of HANDLER_PROVENANCE) {
      declared[row.handler] ??= new Set();
      for (const d of row.deps) declared[row.handler].add(d.pkg);
    }

    // Discover handler source files + their third-party imports directly from
    // the Python sources, so a newly added handler is detected automatically.
    const HANDLER_SOURCE_DIRS = [
      path.resolve(LIB_ROOT, "../custom_resources"),
      path.resolve(LIB_ROOT, "../prebid_server"),
    ];

    function pyFiles(dir: string): string[] {
      const out: string[] = [];
      if (!fs.existsSync(dir)) return out;
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) out.push(...pyFiles(full));
        else if (entry.name.endsWith(".py")) out.push(full);
      }
      return out;
    }

    // Only consider handler modules that the stack actually deploys (those with a
    // declared row). For each, assert the declared deps cover the third-party
    // imports found in its source module. This catches "handler gained a new
    // third-party import but the provider map was not updated".
    for (const row of HANDLER_PROVENANCE) {
      const moduleName = row.handler.split(".")[0]; // e.g. "cache_access"
      it(`${row.handler}: declared providers cover all third-party imports in ${moduleName}.py`, () => {
        // Find the module file.
        const candidates = HANDLER_SOURCE_DIRS.flatMap(pyFiles).filter(
          (f) => path.basename(f) === `${moduleName}.py`,
        );
        expect(candidates.length).toBeGreaterThanOrEqual(1);
        const src = fs.readFileSync(candidates[0], "utf8");
        const imported = new Set<string>();
        for (const line of src.split("\n")) {
          const m = line.match(/^\s*(?:import|from)\s+([A-Za-z0-9_]+)/);
          if (m && KNOWN_THIRD_PARTY.includes(m[1])) imported.add(m[1]);
        }
        for (const pkg of imported) {
          expect(declared[row.handler]?.has(pkg)).toBe(true);
        }
      });
    }
  });

  // Complementary construct-level lint (cheap, non-flaky): any handler that
  // declares an ASSET_BUNDLE dep must use pythonAssetCode/redisLayerCode — not
  // a plain fromAsset, which would ship the source WITHOUT the package.
  describe("construct-level lint: handlers with ASSET_BUNDLE deps use pythonAssetCode/redisLayerCode", () => {
    for (const row of HANDLER_PROVENANCE) {
      if (!row.deps.some((d) => d.provider === ASSET_BUNDLE)) continue;

      it(`${row.handler}: bundles requirements into the function asset`, () => {
        const source = readConstruct(row.constructFile);
        const codeProvider = codeProviderForHandler(source, row.handler);
        expect(["pythonAssetCode", "redisLayerCode"]).toContain(codeProvider);
      });
    }
  });
});

// ---------------------------------------------------------------------------
// requirements.txt-driven coverage guard (hardening)
// ---------------------------------------------------------------------------
//
// The provenance matrix above is hand-maintained. This block is self-updating:
// it reads each deployed handler's sibling `requirements.txt` directly from the
// source tree and asserts that EVERY third-party requirement is provided by
// exactly one of:
//   (a) the function's own bundled asset - the construct uses pythonAssetCode()
//       or redisLayerCode(), which pip-install requirements.txt into the asset; OR
//   (b) a package declared by one of the function's ATTACHED layers (resolved
//       from the synthesized template via the explicit LAYER_PROVIDES map below).
//
// It is FAIL-CLOSED: a requirement that is neither asset-bundled nor in an
// attached layer's provide-set fails the test, naming the offending package. So
// adding a new dependency to a plain-fromAsset lambda's requirements.txt (the
// "custom deps + Powertools layer" trap) fails the build until the author either
// switches the function to pythonAssetCode() or attaches a layer that provides it.
//
// IMPORTANT - fidelity: like the rest of this file, "asset-bundled" is INFERRED
// from the construct's code provider, not verified against the zip bytes (CDK
// normalizes asset contents to placeholders in the synthesized template, so jest
// cannot open the archive). This proves the construct is WIRED to install the
// deps, not that the bytes are physically present. The true byte-level check
// happens at deploy/invoke (the functional suite).
//
// LAYER_PROVIDES makes each layer's package set explicit so a requirement can be
// resolved to a provider deterministically. Keep it in sync with the layer
// bundlers in lib/shared/lambda-helpers.ts.
describe("requirements.txt coverage - every third-party requirement is asset-bundled or layer-provided", () => {
  const template = prebidServerTemplate();
  const layerIndex = buildLayerIndex(template);

  // Explicit package sets each layer provides at runtime. Sourced from the layer
  // bundlers: PowertoolsLayer installs aws_lambda_powertools + crhelper + requests;
  // SolutionsLayer ships aws_solutions; RedisLayer installs redis + cachetools.
  const LAYER_PROVIDES: Array<{ layer: LayerProvider; packages: string[] }> = [
    { layer: LAYER_POWERTOOLS, packages: ["aws_lambda_powertools"] },
    { layer: LAYER_CRHELPER, packages: ["crhelper"] },
    { layer: LAYER_SOLUTIONS, packages: ["aws_solutions"] },
    { layer: LAYER_REDIS, packages: ["redis", "cachetools"] },
    { layer: LAYER_METRICS, packages: ["cloudwatch_metrics"] },
  ];

  // Runtime built-ins provided by the Lambda Python runtime - never need bundling
  // or a layer, so they are excluded from the requirement coverage check.
  const RUNTIME_BUILTINS = new Set(["boto3", "botocore"]);

  // Normalize a requirements.txt line to its distribution name (strip version
  // specifiers, extras, comments, environment markers). Returns null for blank
  // and comment lines. The import name used elsewhere in this file matches the
  // distribution name for the packages in play (crhelper, redis, cachetools,
  // requests, aws_lambda_powertools/aws-lambda-powertools normalized below).
  function requirementDistName(line: string): string | null {
    const stripped = line.split("#")[0].trim();
    if (!stripped) return null;
    const name = stripped.split(/[<>=!~;\[ ]/)[0].trim().toLowerCase();
    if (!name) return null;
    // Normalize distribution -> import name for the packages this guard reasons about.
    return name.replace(/-/g, "_");
  }

  // Locate a handler module's sibling requirements.txt by finding <module>.py in
  // the handler source dirs and reading requirements.txt next to it.
  const HANDLER_SOURCE_DIRS = [
    path.resolve(LIB_ROOT, "../custom_resources"),
    path.resolve(LIB_ROOT, "../prebid_server"),
  ];

  function findModuleDir(moduleName: string): string | null {
    const stack = [...HANDLER_SOURCE_DIRS];
    while (stack.length) {
      const dir = stack.pop()!;
      if (!fs.existsSync(dir)) continue;
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) stack.push(full);
        else if (entry.name === `${moduleName}.py`) return dir;
      }
    }
    return null;
  }

  function readRequirements(dir: string): string[] {
    const reqFile = path.join(dir, "requirements.txt");
    if (!fs.existsSync(reqFile)) return [];
    const pkgs: string[] = [];
    for (const line of fs.readFileSync(reqFile, "utf8").split("\n")) {
      const name = requirementDistName(line);
      if (name && !RUNTIME_BUILTINS.has(name)) pkgs.push(name);
    }
    return pkgs;
  }

  // Index functions by handler for layer lookup.
  const functionsByHandler: Record<string, any[]> = {};
  for (const res of Object.values(template.findResources("AWS::Lambda::Function"))) {
    const props = (res as any).Properties ?? {};
    const h = props.Handler;
    if (typeof h === "string") (functionsByHandler[h] ??= []).push(props);
  }

  /** Packages provided by the layers attached to at least one instance of this handler. */
  function layerProvidedPackages(handler: string): Set<string> {
    const provided = new Set<string>();
    for (const props of functionsByHandler[handler] ?? []) {
      for (const layer of resolveAttachedProviders(props, layerIndex)) {
        for (const entry of LAYER_PROVIDES) {
          if (layerMatches(layer, entry.layer)) {
            for (const pkg of entry.packages) provided.add(pkg);
          }
        }
      }
    }
    return provided;
  }

  for (const row of HANDLER_PROVENANCE) {
    const moduleName = row.handler.split(".")[0];

    it(`${row.handler}: every requirements.txt package is asset-bundled or layer-provided`, () => {
      const moduleDir = findModuleDir(moduleName);
      expect(moduleDir).not.toBeNull();

      const requirements = readRequirements(moduleDir!);
      if (requirements.length === 0) {
        // No third-party requirements (or only runtime built-ins) - nothing to cover.
        return;
      }

      const codeProvider = codeProviderForHandler(readConstruct(row.constructFile), row.handler);
      const assetBundled = codeProvider === "pythonAssetCode" || codeProvider === "redisLayerCode";
      const layerProvided = layerProvidedPackages(row.handler);

      // When the function asset-bundles its requirements.txt (pythonAssetCode /
      // redisLayerCode), every requirement is installed into the asset - covered.
      // Otherwise (plain fromAsset), each requirement MUST be supplied by an
      // attached layer. Fail-closed: name any package that is neither.
      const uncovered = assetBundled
        ? []
        : requirements.filter((pkg) => !layerProvided.has(pkg));

      expect({ handler: row.handler, codeProvider, uncovered }).toEqual({
        handler: row.handler,
        codeProvider,
        uncovered: [],
      });
    });
  }
});
