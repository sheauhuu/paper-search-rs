#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  loadPackageMetadata,
  repoRoot,
  validatePackageMetadata,
} from "./release-contract.mjs";

const tagIndex = process.argv.indexOf("--tag");
const tag =
  tagIndex >= 0
    ? process.argv[tagIndex + 1]
    : process.env.GITHUB_REF_TYPE === "tag"
      ? process.env.GITHUB_REF_NAME
      : undefined;
if (tagIndex >= 0 && !tag) {
  throw new Error("--tag requires a value");
}

const metadata = await loadPackageMetadata();
const version = validatePackageMetadata({ ...metadata, tag });
const pyproject = await readFile(path.join(repoRoot, "pyproject.toml"), "utf8");
if (!/^name = "paper-search-rs"$/m.test(pyproject)) {
  throw new Error("pyproject.toml project name must be paper-search-rs");
}
if (!/^bindings = "bin"$/m.test(pyproject)) {
  throw new Error('pyproject.toml must use Maturin bindings = "bin"');
}
if (!/^dynamic = \["version"\]$/m.test(pyproject)) {
  throw new Error("pyproject.toml must derive its version from Cargo");
}

process.stdout.write(`release metadata is consistent at ${version}\n`);
