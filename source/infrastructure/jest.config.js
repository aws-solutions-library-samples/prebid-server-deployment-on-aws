// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  roots: ["<rootDir>/test"],
  testMatch: ["**/test/**/*.test.ts"],
  // Type-check tests against tsconfig.test.json (noEmit) so the production
  // `tsc` build (tsconfig.json) stays limited to app.ts + lib/ and never
  // emits test JS into dist/ or fails the release build on a test type error.
  transform: {
    "^.+\\.tsx?$": ["ts-jest", { tsconfig: "tsconfig.test.json" }],
  },
  // Coverage: emit Cobertura XML into coverage/ for coverage tooling, plus a
  // text summary for local runs. Scope collection to the app sources (app.ts entry point + lib/),
  // excluding generated .d.ts, so coverage reflects construct code rather than tests.
  coverageDirectory: "coverage",
  coverageReporters: ["cobertura", "text-summary"],
  collectCoverageFrom: ["app.ts", "lib/**/*.ts", "!**/*.d.ts"],
};
