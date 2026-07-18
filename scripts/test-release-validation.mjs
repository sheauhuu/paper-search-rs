#!/usr/bin/env node

import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  artifactSpecifications,
  isDirectExecution,
  validateArtifactSet,
  verifyChecksums,
  writeChecksums,
} from "./release-artifacts.mjs";
import { PLATFORM_ENTRIES, validatePackageMetadata } from "./release-contract.mjs";

function fixtureMetadata(version = "0.2.0") {
  const platformManifests = new Map(
    PLATFORM_ENTRIES.map((entry) => [
      `${entry.platform}-${entry.arch}`,
      {
        name: entry.packageName,
        version,
        os: [entry.platform],
        cpu: [entry.arch],
      },
    ]),
  );
  return {
    cargoPackage: {
      name: "paper-search-rs",
      version,
      targets: [{ name: "paper-search-rs", kind: ["bin"] }],
    },
    mainManifest: {
      name: "paper-search-rs",
      version,
      bin: { "paper-search-rs": "bin/paper-search-rs.cjs" },
      optionalDependencies: Object.fromEntries(
        PLATFORM_ENTRIES.map((entry) => [entry.packageName, version]),
      ),
    },
    platformManifests,
  };
}

function artifactName(specification) {
  if (specification.kind === "npm-main") {
    return "paper-search-rs-0.2.0.tgz";
  }
  const entry = PLATFORM_ENTRIES.find(
    (candidate) => candidate.rustTarget === specification.target,
  );
  if (specification.kind === "native") {
    const extension = entry.platform === "win32" ? "zip" : "tar.gz";
    return `paper-search-rs-0.2.0-${entry.rustTarget}.${extension}`;
  }
  if (specification.kind === "npm") {
    return `${entry.packageName}-0.2.0.tgz`;
  }
  const suffix =
    entry.platform === "darwin"
      ? `macosx_11_0_${entry.arch === "x64" ? "x86_64" : "arm64"}`
      : entry.platform === "linux"
        ? `manylinux_2_28_${entry.arch === "x64" ? "x86_64" : "aarch64"}`
        : "win_amd64";
  return `paper_search_rs-0.2.0-py3-none-${suffix}.whl`;
}

test("accepts consistent Cargo, npm, platform, and tag versions", () => {
  assert.equal(
    validatePackageMetadata({ ...fixtureMetadata(), tag: "v0.2.0" }),
    "0.2.0",
  );
});

test("detects direct CLI execution from a Windows file URL", () => {
  const script = String.raw`D:\a\paper-search-rs\scripts\release-artifacts.mjs`;
  const moduleUrl = "file:///D:/a/paper-search-rs/scripts/release-artifacts.mjs";
  assert.equal(isDirectExecution(script, moduleUrl, "win32"), true);
  assert.equal(
    isDirectExecution(String.raw`D:\a\paper-search-rs\scripts\other.mjs`, moduleUrl, "win32"),
    false,
  );
});

test("packs the main npm package from an explicit local path", async () => {
  const workflow = await readFile(
    new URL("../.github/workflows/ci.yml", import.meta.url),
    "utf8",
  );
  assert.match(
    workflow,
    /^\s+npm pack \.\/npm --ignore-scripts --pack-destination assembled$/m,
  );
  assert.doesNotMatch(
    workflow,
    /^\s+npm pack npm --ignore-scripts --pack-destination assembled$/m,
  );
});

test("publishes npm tarballs from explicit local paths", async () => {
  const workflow = await readFile(
    new URL("../.github/workflows/ci.yml", import.meta.url),
    "utf8",
  );
  assert.match(
    workflow,
    /^\s+for package in \.\/release\/paper-search-rs-\{darwin-arm64,darwin-x64,linux-arm64,linux-x64,win32-x64\}-\*\.tgz; do$/m,
  );
  assert.match(
    workflow,
    /^\s+npm publish "\.\/release\/paper-search-rs-\$\{version\}\.tgz" --access public --provenance$/m,
  );
  assert.doesNotMatch(workflow, /npm publish "?release\/paper-search-rs-/);
});

test("uses Node 24 artifact actions", async () => {
  const workflow = await readFile(
    new URL("../.github/workflows/ci.yml", import.meta.url),
    "utf8",
  );
  assert.equal(workflow.match(/actions\/upload-artifact@v5/g)?.length, 2);
  assert.equal(workflow.match(/actions\/download-artifact@v5/g)?.length, 2);
  assert.doesNotMatch(workflow, /actions\/(?:upload|download)-artifact@v4/);
});

test("rejects version and target mapping drift", () => {
  const metadata = fixtureMetadata();
  metadata.mainManifest.optionalDependencies["paper-search-rs-linux-x64"] = "0.2.1";
  assert.throws(
    () => validatePackageMetadata({ ...metadata, tag: "v0.2.1" }),
    /optionalDependencies.*\nrelease tag v0\.2\.1 does not match v0\.2\.0/s,
  );
});

test("generates checksums and detects corruption", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "paper-search-rs-artifacts-"));
  try {
    for (const specification of artifactSpecifications("0.2.0")) {
      const name = artifactName(specification);
      await writeFile(path.join(directory, name), `${name}\n`);
    }
    const files = await validateArtifactSet(directory, "0.2.0");
    assert.equal(files.length, 16);
    await writeChecksums(directory, files);
    await verifyChecksums(directory, files);
    await writeFile(path.join(directory, files[0]), "corrupt\n");
    await assert.rejects(() => verifyChecksums(directory, files), /checksum mismatch/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("rejects missing and unexpected artifacts", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "paper-search-rs-artifacts-"));
  try {
    const specifications = artifactSpecifications("0.2.0");
    for (const specification of specifications.slice(1)) {
      const name = artifactName(specification);
      await writeFile(path.join(directory, name), `${name}\n`);
    }
    await assert.rejects(
      () => validateArtifactSet(directory, "0.2.0"),
      /expected one native artifact/,
    );
    await writeFile(path.join(directory, artifactName(specifications[0])), "restored\n");
    await writeFile(path.join(directory, "unexpected.txt"), "unexpected\n");
    await assert.rejects(
      () => validateArtifactSet(directory, "0.2.0"),
      /unexpected release artifacts: unexpected\.txt/,
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
