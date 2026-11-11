// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
import { execFileSync } from "child_process";
import { readFileSync } from "fs";
import * as path from "path";

/**
 * Docker config static checks (Requirements 3.3, 3.4, 3.5, 3.6).
 *
 * These are static/config assertions over the real deployment container build
 * tooling — they read the actual Dockerfiles and docker-build-config.json and
 * exercise the build script's base-selection contract via its --dry-run path
 * (which validates --base and resolves the Dockerfile BEFORE any Docker
 * invocation, so no Docker daemon is required).
 *
 * Verified properties:
 *   - 3.3 Alpine base applies jlink tuning (custom JRE, strip debug/man/header,
 *         compress modules).
 *   - 3.4 The build tooling defaults to AL2023 when no --base is selected.
 *   - 3.5 An unsupported --base value fails with an error naming the invalid
 *         value.
 *   - 3.6 The Alpine image preserves the musl/zlib CVE upgrade
 *         (CVE-2026-40200 / CVE-2026-6042 / CVE-2026-27171).
 *   - INCLUDE_AMT_BIDDER build arg is present on both Dockerfile bases.
 *
 * Placed in the TS test harness (jest + ts-jest) alongside the CDK unit tests
 * so `npm test` is the single entry point for V2_Branch verification.
 */

// The infrastructure package (jest rootDir) is source/infrastructure; the
// container build tooling lives at deployment/ecr relative to the repo root,
// i.e. two levels up from here.
const ECR_DIR = path.resolve(__dirname, "../../../../../deployment/ecr");
const DOCKER_DIR = path.join(ECR_DIR, "prebid-server");
const BUILD_SCRIPT = path.join(ECR_DIR, "build-image.sh");
const CONFIG_FILE = path.join(DOCKER_DIR, "docker-build-config.json");
const DOCKERFILE_ALPINE = path.join(DOCKER_DIR, "Dockerfile.alpine");
const DOCKERFILE_AL2023 = path.join(DOCKER_DIR, "Dockerfile.al2023");

function read(file: string): string {
  return readFileSync(file, "utf8");
}

describe("Docker dual-base config (Req 3.3, 3.4, 3.5, 3.6)", () => {
  describe("Alpine base retains jlink tuning (Req 3.3)", () => {
    const dockerfile = read(DOCKERFILE_ALPINE);

    it("invokes jlink to build a custom JRE into /custom-java-runtime", () => {
      expect(dockerfile).toMatch(/jlink/);
      expect(dockerfile).toMatch(/--output\s+\/custom-java-runtime/);
    });

    it("applies each jlink minimization flag", () => {
      // Custom module set + the four tuning flags from Req 3.3 / design §3.
      expect(dockerfile).toMatch(/--add-modules/);
      expect(dockerfile).toMatch(/--strip-debug/);
      expect(dockerfile).toMatch(/--no-man-pages/);
      expect(dockerfile).toMatch(/--no-header-files/);
      expect(dockerfile).toMatch(/--compress=2/);
    });

    it("consumes the custom runtime in the deploy stage", () => {
      // The tuned runtime must actually be used by the deploy image, not just built.
      expect(dockerfile).toMatch(/\/custom-java-runtime\s+\/usr\/lib\/jvm\/java-custom/);
      expect(dockerfile).toMatch(/JAVA_HOME=\/usr\/lib\/jvm\/java-custom/);
    });
  });

  describe("Alpine base preserves the musl/zlib CVE upgrade (Req 3.6)", () => {
    const dockerfile = read(DOCKERFILE_ALPINE);

    it("upgrades musl, musl-utils, and zlib via apk upgrade", () => {
      // Order-insensitive: assert each package appears on an `apk ... upgrade` line.
      const upgradeLine = dockerfile
        .split("\n")
        .find((l) => /apk\b.*\bupgrade\b/.test(l));
      expect(upgradeLine).toBeDefined();
      expect(upgradeLine).toMatch(/\bmusl\b/);
      expect(upgradeLine).toMatch(/\bmusl-utils\b/);
      expect(upgradeLine).toMatch(/\bzlib\b/);
    });

    it("documents the CVEs the upgrade addresses", () => {
      expect(dockerfile).toMatch(/CVE-2026-40200/);
      expect(dockerfile).toMatch(/CVE-2026-6042/);
      expect(dockerfile).toMatch(/CVE-2026-27171/);
    });
  });

  describe("INCLUDE_AMT_BIDDER present on both bases", () => {
    it("declares the INCLUDE_AMT_BIDDER build arg and uses it in Dockerfile.alpine", () => {
      const dockerfile = read(DOCKERFILE_ALPINE);
      expect(dockerfile).toMatch(/ARG\s+INCLUDE_AMT_BIDDER/);
      expect(dockerfile).toMatch(/INCLUDE_AMT_BIDDER"?\s*=\s*"?true/);
    });

    it("declares the INCLUDE_AMT_BIDDER build arg and uses it in Dockerfile.al2023", () => {
      const dockerfile = read(DOCKERFILE_AL2023);
      expect(dockerfile).toMatch(/ARG\s+INCLUDE_AMT_BIDDER/);
      expect(dockerfile).toMatch(/INCLUDE_AMT_BIDDER"?\s*=\s*"?true/);
    });
  });

  describe("AL2023 base composition (Req 3 default path)", () => {
    const dockerfile = read(DOCKERFILE_AL2023);

    it("uses the Corretto AL2023 build stage and AL2023-minimal deploy stage", () => {
      expect(dockerfile).toMatch(/amazoncorretto:21-al2023\s+AS\s+build/);
      expect(dockerfile).toMatch(/amazonlinux:2023-minimal\s+AS\s+deploy/);
    });

    it("also applies jlink tuning on the AL2023 path", () => {
      expect(dockerfile).toMatch(/jlink/);
      expect(dockerfile).toMatch(/--strip-debug/);
      expect(dockerfile).toMatch(/--compress=2/);
      expect(dockerfile).toMatch(/--output\s+\/custom-java-runtime/);
    });
  });

  describe("base-selection contract in docker-build-config.json", () => {
    const config = JSON.parse(read(CONFIG_FILE)) as {
      DEFAULT_BASE: string;
      SUPPORTED_BASES: string[];
      BASE_DOCKERFILES: Record<string, string>;
    };

    it("defaults to al2023 (Req 3.4)", () => {
      expect(config.DEFAULT_BASE).toBe("al2023");
    });

    it("declares exactly the closed set {al2023, alpine} (Req 3.1, 3.2, 3.5)", () => {
      expect([...config.SUPPORTED_BASES].sort()).toEqual(["al2023", "alpine"]);
    });

    it("maps each supported base to an existing Dockerfile in the build dir", () => {
      for (const base of config.SUPPORTED_BASES) {
        const dockerfileName = config.BASE_DOCKERFILES[base];
        expect(dockerfileName).toBeDefined();
        // The mapped Dockerfile must actually exist on disk.
        expect(() => read(path.join(DOCKER_DIR, dockerfileName))).not.toThrow();
      }
    });
  });

  describe("build script base-selection behavior (Req 3.4, 3.5)", () => {
    // Use --dry-run so the script validates --base and resolves the Dockerfile
    // WITHOUT invoking Docker (no daemon required). The script prints the
    // resolved Dockerfile name to stdout on success and exits non-zero on an
    // unsupported base.
    function runBuildScript(args: string[]): { status: number; stdout: string; stderr: string } {
      try {
        const stdout = execFileSync("bash", [BUILD_SCRIPT, ...args, "--dry-run"], {
          encoding: "utf8",
          stdio: ["ignore", "pipe", "pipe"],
        });
        return { status: 0, stdout, stderr: "" };
      } catch (err: unknown) {
        const e = err as { status?: number; stdout?: Buffer | string; stderr?: Buffer | string };
        return {
          status: typeof e.status === "number" ? e.status : 1,
          stdout: e.stdout ? e.stdout.toString() : "",
          stderr: e.stderr ? e.stderr.toString() : "",
        };
      }
    }

    it("defaults to al2023 when no --base is supplied (Req 3.4)", () => {
      const { status, stdout } = runBuildScript([]);
      expect(status).toBe(0);
      // Resolved Dockerfile emitted on stdout is the AL2023 one.
      expect(stdout).toMatch(/Dockerfile\.al2023/);
    });

    it("resolves Dockerfile.alpine when --base alpine is supplied", () => {
      const { status, stdout } = runBuildScript(["--base", "alpine"]);
      expect(status).toBe(0);
      expect(stdout).toMatch(/Dockerfile\.alpine/);
    });

    it("rejects an unsupported --base value, naming the invalid value (Req 3.5)", () => {
      const invalid = "ubuntu";
      const { status, stdout, stderr } = runBuildScript(["--base", invalid]);
      expect(status).not.toBe(0);
      // The error must name the offending value so the failure is actionable.
      expect(stdout + stderr).toContain(invalid);
    });
  });
});
