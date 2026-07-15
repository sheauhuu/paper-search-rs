import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
export const { PLATFORM_ENTRIES } = require("../npm/lib/platform.cjs");
export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export async function readJson(file) {
  return JSON.parse(await readFile(file, "utf8"));
}

export function cargoRootPackage() {
  const metadata = JSON.parse(
    execFileSync("cargo", ["metadata", "--format-version", "1", "--no-deps"], {
      cwd: repoRoot,
      encoding: "utf8",
    }),
  );
  const manifestPath = path.join(repoRoot, "Cargo.toml");
  const cargoPackage = metadata.packages.find(
    (candidate) => candidate.manifest_path === manifestPath,
  );
  if (!cargoPackage) {
    throw new Error(`Cargo metadata did not contain ${manifestPath}`);
  }
  return cargoPackage;
}

export function validatePackageMetadata({
  cargoPackage,
  mainManifest,
  platformManifests,
  tag,
}) {
  const errors = [];
  const version = cargoPackage.version;
  if (cargoPackage.name !== "paper-search-rs") {
    errors.push(`Cargo package must be paper-search-rs, got ${cargoPackage.name}`);
  }
  if (
    !cargoPackage.targets.some(
      (target) => target.name === "paper-search-rs" && target.kind.includes("bin"),
    )
  ) {
    errors.push("Cargo package must expose the paper-search-rs binary");
  }
  if (mainManifest.name !== "paper-search-rs") {
    errors.push(`npm main package must be paper-search-rs, got ${mainManifest.name}`);
  }
  if (mainManifest.version !== version) {
    errors.push(
      `npm main version ${mainManifest.version} does not match Cargo ${version}`,
    );
  }
  if (mainManifest.bin?.["paper-search-rs"] !== "bin/paper-search-rs.cjs") {
    errors.push("npm main package must expose bin/paper-search-rs.cjs");
  }

  const expectedDependencies = Object.fromEntries(
    PLATFORM_ENTRIES.map((entry) => [entry.packageName, version]),
  );
  const actualDependencies = mainManifest.optionalDependencies ?? {};
  if (JSON.stringify(actualDependencies) !== JSON.stringify(expectedDependencies)) {
    errors.push("npm optionalDependencies do not exactly match the release target set");
  }

  const manifestNames = new Set();
  for (const entry of PLATFORM_ENTRIES) {
    const key = `${entry.platform}-${entry.arch}`;
    const manifest = platformManifests.get(key);
    if (!manifest) {
      errors.push(`missing npm platform manifest for ${key}`);
      continue;
    }
    if (manifestNames.has(manifest.name)) {
      errors.push(`duplicate npm platform package name ${manifest.name}`);
    }
    manifestNames.add(manifest.name);
    if (manifest.name !== entry.packageName) {
      errors.push(`${key} package must be ${entry.packageName}, got ${manifest.name}`);
    }
    if (manifest.version !== version) {
      errors.push(`${entry.packageName} version must be ${version}, got ${manifest.version}`);
    }
    if (JSON.stringify(manifest.os) !== JSON.stringify([entry.platform])) {
      errors.push(`${entry.packageName} has an invalid os field`);
    }
    if (JSON.stringify(manifest.cpu) !== JSON.stringify([entry.arch])) {
      errors.push(`${entry.packageName} has an invalid cpu field`);
    }
  }
  if (platformManifests.size !== PLATFORM_ENTRIES.length) {
    errors.push(
      `expected ${PLATFORM_ENTRIES.length} npm platform manifests, got ${platformManifests.size}`,
    );
  }

  if (tag && tag !== `v${version}`) {
    errors.push(`release tag ${tag} does not match v${version}`);
  }
  if (errors.length > 0) {
    throw new Error(errors.join("\n"));
  }
  return version;
}

export async function loadPackageMetadata() {
  const platformManifests = new Map();
  for (const entry of PLATFORM_ENTRIES) {
    const key = `${entry.platform}-${entry.arch}`;
    platformManifests.set(
      key,
      await readJson(path.join(repoRoot, "npm", "packages", key, "package.json")),
    );
  }
  return {
    cargoPackage: cargoRootPackage(),
    mainManifest: await readJson(path.join(repoRoot, "npm", "package.json")),
    platformManifests,
  };
}
