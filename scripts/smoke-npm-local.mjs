#!/usr/bin/env node

import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const require = createRequire(import.meta.url);
const { selectPlatform } = require("../npm/lib/platform.cjs");
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd ?? repoRoot,
      env: options.env ?? process.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.once("error", reject);
    child.once("close", (code, signal) => {
      resolve({ code, signal, stdout, stderr });
    });
    if (options.input === undefined) {
      child.stdin.end();
    } else {
      child.stdin.end(options.input);
    }
  });
}

async function runChecked(command, args, options) {
  const result = await run(command, args, options);
  assert.equal(
    result.code,
    0,
    `${command} ${args.join(" ")} failed\n${result.stderr}`,
  );
  return result;
}

function parsePackResult(stdout) {
  const result = JSON.parse(stdout);
  assert.equal(result.length, 1);
  return result[0];
}

function assertPackageFiles(pack, allowedPatterns) {
  for (const file of pack.files) {
    assert.ok(
      allowedPatterns.some((pattern) => pattern.test(file.path)),
      `unexpected file in ${pack.filename}: ${file.path}`,
    );
  }
}

const metadata = JSON.parse(
  (await runChecked("cargo", ["metadata", "--format-version", "1", "--no-deps"]))
    .stdout,
);
const rootPackage = metadata.packages.find(
  (candidate) => candidate.manifest_path === path.join(repoRoot, "Cargo.toml"),
);
assert.ok(rootPackage, "Cargo root package was not found");

const platformEntry = selectPlatform();
const binary = path.join(
  repoRoot,
  "target",
  "release",
  platformEntry.binaryName,
);
await runChecked("node", [
  path.join(repoRoot, "scripts", "stage-npm-binary.mjs"),
  platformEntry.rustTarget,
  binary,
]);

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), "paper-search-rs-npm-"));
try {
  const npmEnv = {
    ...process.env,
    npm_config_cache: path.join(temporaryRoot, "npm-cache"),
  };
  const platformDirectory = path.join(
    repoRoot,
    "npm",
    "packages",
    `${platformEntry.platform}-${platformEntry.arch}`,
  );
  const platformPack = parsePackResult(
    (
      await runChecked(
        "npm",
        ["pack", "--json", "--ignore-scripts", "--pack-destination", temporaryRoot],
        { cwd: platformDirectory, env: npmEnv },
      )
    ).stdout,
  );
  const mainPack = parsePackResult(
    (
      await runChecked(
        "npm",
        ["pack", "--json", "--ignore-scripts", "--pack-destination", temporaryRoot],
        { cwd: path.join(repoRoot, "npm"), env: npmEnv },
      )
    ).stdout,
  );

  assertPackageFiles(platformPack, [
    /^package\.json$/,
    /^LICENSE$/,
    /^bin\/paper-search-rs(?:\.exe)?$/,
  ]);
  assertPackageFiles(mainPack, [
    /^package\.json$/,
    /^LICENSE$/,
    /^bin\/paper-search-rs\.cjs$/,
    /^lib\/platform\.cjs$/,
  ]);

  const installDirectory = path.join(temporaryRoot, "install");
  const platformTarball = path.join(temporaryRoot, platformPack.filename);
  const mainTarball = path.join(temporaryRoot, mainPack.filename);
  await mkdir(installDirectory);
  await writeFile(
    path.join(installDirectory, "package.json"),
    `${JSON.stringify(
      {
        private: true,
        dependencies: {
          "paper-search-rs": `file:${mainTarball}`,
          [platformEntry.packageName]: `file:${platformTarball}`,
        },
      },
      null,
      2,
    )}\n`,
  );
  await runChecked(
    "npm",
    [
      "install",
      "--ignore-scripts",
      "--omit=optional",
      "--no-audit",
      "--no-fund",
      "--no-package-lock",
    ],
    { cwd: installDirectory, env: npmEnv },
  );

  const smokeEnv = {
    ...npmEnv,
    PAPER_SEARCH_JCR_ENABLED: "false",
    RUST_LOG: "error",
  };
  const version = await runChecked(
    "npx",
    ["--no-install", "paper-search-rs", "--version"],
    { cwd: installDirectory, env: smokeEnv },
  );
  assert.match(version.stdout, new RegExp(`paper-search-rs ${rootPackage.version}`));

  const eof = await runChecked("npx", ["--no-install", "paper-search-rs"], {
    cwd: installDirectory,
    env: smokeEnv,
  });
  assert.equal(eof.stdout, "", "npx launcher contaminated MCP stdout on EOF");

  const installedManifest = JSON.parse(
    await readFile(
      path.join(installDirectory, "node_modules", "paper-search-rs", "package.json"),
      "utf8",
    ),
  );
  assert.equal(installedManifest.version, rootPackage.version);
  process.stderr.write(
    `local npx smoke passed for ${platformEntry.platform}/${platformEntry.arch}\n`,
  );
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}
