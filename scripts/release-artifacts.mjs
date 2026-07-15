#!/usr/bin/env node

import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { PLATFORM_ENTRIES } from "./release-contract.mjs";

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function artifactSpecifications(
  version,
  targets = PLATFORM_ENTRIES,
  includeMainPackage = targets.length === PLATFORM_ENTRIES.length,
) {
  const escapedVersion = escapeRegExp(version);
  const specifications = targets.flatMap((entry) => {
    const archiveExtension = entry.platform === "win32" ? "zip" : "tar.gz";
    const wheelPlatform =
      entry.platform === "darwin"
        ? `macosx_[^/]+_${entry.arch === "x64" ? "x86_64" : "arm64"}`
        : entry.platform === "linux"
          ? `manylinux_[^/]+_${entry.arch === "x64" ? "x86_64" : "aarch64"}`
          : "win_amd64";
    return [
      {
        kind: "native",
        target: entry.rustTarget,
        pattern: new RegExp(
          `^paper-search-rs-${escapedVersion}-${escapeRegExp(entry.rustTarget)}\\.${escapeRegExp(archiveExtension)}$`,
        ),
      },
      {
        kind: "npm",
        target: entry.rustTarget,
        pattern: new RegExp(
          `^${escapeRegExp(entry.packageName)}-${escapedVersion}\\.tgz$`,
        ),
      },
      {
        kind: "wheel",
        target: entry.rustTarget,
        pattern: new RegExp(
          `^paper_search_rs-${escapedVersion}-py3-none-${wheelPlatform}\\.whl$`,
        ),
      },
    ];
  });
  if (includeMainPackage) {
    specifications.push({
      kind: "npm-main",
      target: "all",
      pattern: new RegExp(`^paper-search-rs-${escapedVersion}\\.tgz$`),
    });
  }
  return specifications;
}

export async function validateArtifactSet(
  directory,
  version,
  targets = PLATFORM_ENTRIES,
  includeMainPackage = targets.length === PLATFORM_ENTRIES.length,
) {
  const files = (await readdir(directory, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && entry.name !== "SHA256SUMS")
    .map((entry) => entry.name)
    .sort();
  const specifications = artifactSpecifications(version, targets, includeMainPackage);
  const matched = new Set();
  for (const specification of specifications) {
    const candidates = files.filter((file) => specification.pattern.test(file));
    if (candidates.length !== 1) {
      throw new Error(
        `expected one ${specification.kind} artifact for ${specification.target}, found ${candidates.length}`,
      );
    }
    if (matched.has(candidates[0])) {
      throw new Error(`artifact matched more than one release slot: ${candidates[0]}`);
    }
    matched.add(candidates[0]);
  }
  const unexpected = files.filter((file) => !matched.has(file));
  if (unexpected.length > 0) {
    throw new Error(`unexpected release artifacts: ${unexpected.join(", ")}`);
  }
  return [...matched].sort();
}

async function sha256(file) {
  return createHash("sha256").update(await readFile(file)).digest("hex");
}

export async function writeChecksums(directory, files) {
  const lines = [];
  for (const file of [...files].sort()) {
    lines.push(`${await sha256(path.join(directory, file))}  ${file}`);
  }
  await writeFile(path.join(directory, "SHA256SUMS"), `${lines.join("\n")}\n`);
}

export async function verifyChecksums(directory, files) {
  const checksumText = await readFile(path.join(directory, "SHA256SUMS"), "utf8");
  const entries = checksumText
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const match = /^([a-f0-9]{64})  ([^/]+)$/.exec(line);
      if (!match) {
        throw new Error(`invalid SHA256SUMS line: ${line}`);
      }
      return { hash: match[1], file: match[2] };
    });
  if (new Set(entries.map((entry) => entry.file)).size !== entries.length) {
    throw new Error("SHA256SUMS contains duplicate file entries");
  }
  const expectedFiles = [...files].sort();
  const checksumFiles = entries.map((entry) => entry.file).sort();
  if (JSON.stringify(expectedFiles) !== JSON.stringify(checksumFiles)) {
    throw new Error("SHA256SUMS does not match the validated artifact set");
  }
  for (const entry of entries) {
    const actual = await sha256(path.join(directory, entry.file));
    if (actual !== entry.hash) {
      throw new Error(`checksum mismatch for ${entry.file}`);
    }
  }
}

async function main() {
  const [directoryArgument, ...args] = process.argv.slice(2);
  if (!directoryArgument) {
    throw new Error(
      "usage: node scripts/release-artifacts.mjs <directory> --version <version> [--target <rust-target>] [--write]",
    );
  }
  const versionIndex = args.indexOf("--version");
  const version = versionIndex >= 0 ? args[versionIndex + 1] : undefined;
  if (!version) {
    throw new Error("--version requires a value");
  }
  const targetIndex = args.indexOf("--target");
  let targets = PLATFORM_ENTRIES;
  if (targetIndex >= 0) {
    const target = args[targetIndex + 1];
    targets = PLATFORM_ENTRIES.filter((entry) => entry.rustTarget === target);
    if (targets.length !== 1) {
      throw new Error(`unsupported Rust target: ${target}`);
    }
  }
  const directory = path.resolve(directoryArgument);
  const files = await validateArtifactSet(
    directory,
    version,
    targets,
    targetIndex < 0,
  );
  if (args.includes("--write")) {
    await writeChecksums(directory, files);
  }
  await verifyChecksums(directory, files);
  process.stdout.write(`verified ${files.length} release artifacts\n`);
}

if (path.resolve(process.argv[1] ?? "") === path.resolve(new URL(import.meta.url).pathname)) {
  await main();
}
