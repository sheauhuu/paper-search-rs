"use strict";

const path = require("node:path");

const PLATFORM_ENTRIES = Object.freeze([
  Object.freeze({
    platform: "darwin",
    arch: "arm64",
    packageName: "paper-search-rs-darwin-arm64",
    rustTarget: "aarch64-apple-darwin",
    binaryName: "paper-search-rs",
  }),
  Object.freeze({
    platform: "darwin",
    arch: "x64",
    packageName: "paper-search-rs-darwin-x64",
    rustTarget: "x86_64-apple-darwin",
    binaryName: "paper-search-rs",
  }),
  Object.freeze({
    platform: "linux",
    arch: "arm64",
    packageName: "paper-search-rs-linux-arm64",
    rustTarget: "aarch64-unknown-linux-gnu",
    binaryName: "paper-search-rs",
  }),
  Object.freeze({
    platform: "linux",
    arch: "x64",
    packageName: "paper-search-rs-linux-x64",
    rustTarget: "x86_64-unknown-linux-gnu",
    binaryName: "paper-search-rs",
  }),
  Object.freeze({
    platform: "win32",
    arch: "x64",
    packageName: "paper-search-rs-win32-x64",
    rustTarget: "x86_64-pc-windows-msvc",
    binaryName: "paper-search-rs.exe",
  }),
]);

function selectPlatform(platform = process.platform, arch = process.arch) {
  const entry = PLATFORM_ENTRIES.find(
    (candidate) => candidate.platform === platform && candidate.arch === arch,
  );
  if (!entry) {
    throw new Error(
      `paper-search-rs does not support platform ${platform}/${arch}; supported targets: ${PLATFORM_ENTRIES.map((candidate) => `${candidate.platform}/${candidate.arch}`).join(", ")}`,
    );
  }
  return entry;
}

function resolveBinary(
  platform = process.platform,
  arch = process.arch,
  resolvePackage = require.resolve,
) {
  const entry = selectPlatform(platform, arch);
  let manifestPath;
  try {
    manifestPath = resolvePackage(`${entry.packageName}/package.json`);
  } catch (error) {
    const wrapped = new Error(
      `paper-search-rs could not find the optional package ${entry.packageName}; reinstall paper-search-rs for ${platform}/${arch}`,
    );
    wrapped.cause = error;
    throw wrapped;
  }
  return path.join(path.dirname(manifestPath), "bin", entry.binaryName);
}

module.exports = { PLATFORM_ENTRIES, resolveBinary, selectPlatform };
