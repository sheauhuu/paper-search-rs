#!/usr/bin/env node

import { chmod, copyFile, mkdir, stat } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { PLATFORM_ENTRIES } = require("../npm/lib/platform.cjs");
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const [rustTarget, sourceArgument] = process.argv.slice(2);
if (!rustTarget || !sourceArgument) {
  throw new Error(
    "usage: node scripts/stage-npm-binary.mjs <rust-target> <binary-path>",
  );
}

const entry = PLATFORM_ENTRIES.find(
  (candidate) => candidate.rustTarget === rustTarget,
);
if (!entry) {
  throw new Error(`unsupported Rust target: ${rustTarget}`);
}

const source = path.resolve(sourceArgument);
const sourceStat = await stat(source);
if (!sourceStat.isFile() || sourceStat.size === 0) {
  throw new Error(`native binary is missing or empty: ${source}`);
}

const packageDirectory = path.join(
  repoRoot,
  "npm",
  "packages",
  `${entry.platform}-${entry.arch}`,
);
const binDirectory = path.join(packageDirectory, "bin");
const destination = path.join(binDirectory, entry.binaryName);
await mkdir(binDirectory, { recursive: true });
await copyFile(source, destination);
await copyFile(path.join(repoRoot, "LICENSE"), path.join(packageDirectory, "LICENSE"));
if (entry.platform !== "win32") {
  await chmod(destination, 0o755);
}

process.stderr.write(`staged ${rustTarget} binary at ${destination}\n`);
