"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const {
  PLATFORM_ENTRIES,
  resolveBinary,
  selectPlatform,
} = require("../lib/platform.cjs");

test("maps every supported Node platform to one Rust target", () => {
  assert.deepEqual(
    PLATFORM_ENTRIES.map(({ platform, arch, rustTarget, packageName }) => ({
      platform,
      arch,
      rustTarget,
      packageName,
    })),
    [
      {
        platform: "darwin",
        arch: "arm64",
        rustTarget: "aarch64-apple-darwin",
        packageName: "paper-search-rs-darwin-arm64",
      },
      {
        platform: "darwin",
        arch: "x64",
        rustTarget: "x86_64-apple-darwin",
        packageName: "paper-search-rs-darwin-x64",
      },
      {
        platform: "linux",
        arch: "arm64",
        rustTarget: "aarch64-unknown-linux-gnu",
        packageName: "paper-search-rs-linux-arm64",
      },
      {
        platform: "linux",
        arch: "x64",
        rustTarget: "x86_64-unknown-linux-gnu",
        packageName: "paper-search-rs-linux-x64",
      },
      {
        platform: "win32",
        arch: "x64",
        rustTarget: "x86_64-pc-windows-msvc",
        packageName: "paper-search-rs-win32-x64",
      },
    ],
  );
});

test("rejects unsupported platform and architecture combinations", () => {
  assert.throws(
    () => selectPlatform("freebsd", "x64"),
    /does not support platform freebsd\/x64/,
  );
  assert.throws(
    () => selectPlatform("win32", "arm64"),
    /does not support platform win32\/arm64/,
  );
});

test("resolves the executable inside the optional package", () => {
  const binary = resolveBinary("darwin", "arm64", (specifier) => {
    assert.equal(specifier, "paper-search-rs-darwin-arm64/package.json");
    return path.join("", "tmp", "platform-package", "package.json");
  });
  assert.equal(
    binary,
    path.join("", "tmp", "platform-package", "bin", "paper-search-rs"),
  );
});

test("selects the Windows executable suffix", () => {
  const binary = resolveBinary("win32", "x64", () =>
    path.join("C:\\", "platform-package", "package.json"),
  );
  assert.equal(path.basename(binary), "paper-search-rs.exe");
});

test("reports a missing platform package without leaking module internals", () => {
  assert.throws(
    () =>
      resolveBinary("linux", "x64", () => {
        throw new Error("MODULE_NOT_FOUND");
      }),
    /could not find the optional package paper-search-rs-linux-x64/,
  );
});
