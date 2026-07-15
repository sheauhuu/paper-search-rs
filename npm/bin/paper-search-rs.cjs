#!/usr/bin/env node
"use strict";

const { spawn } = require("node:child_process");
const { resolveBinary } = require("../lib/platform.cjs");

function fatal(error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`paper-search-rs: ${message}\n`);
  process.exitCode = 1;
}

let child;
try {
  child = spawn(resolveBinary(), process.argv.slice(2), {
    env: process.env,
    stdio: "inherit",
    windowsHide: false,
  });
} catch (error) {
  fatal(error);
}

if (child) {
  const forwardedSignals = ["SIGINT", "SIGTERM"];
  const handlers = new Map();

  for (const signal of forwardedSignals) {
    const handler = () => {
      if (!child.killed) {
        child.kill(signal);
      }
    };
    handlers.set(signal, handler);
    process.on(signal, handler);
  }

  function removeSignalHandlers() {
    for (const [signal, handler] of handlers) {
      process.removeListener(signal, handler);
    }
  }

  child.once("error", (error) => {
    removeSignalHandlers();
    fatal(error);
  });

  child.once("exit", (code, signal) => {
    removeSignalHandlers();
    if (signal && process.platform !== "win32") {
      process.kill(process.pid, signal);
      return;
    }
    process.exitCode = code ?? 1;
  });
}
