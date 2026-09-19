#!/usr/bin/env node

const MINIMUM_NODE_VERSION = [24, 11, 0];
const SUPPORTED_NODE_MAJOR = 24;
const NODE_RUNTIME_REQUIREMENT = "Node.js 24 LTS (>=24.11.0 <25)";

function parseNodeVersion(value) {
  const match = value.trim().match(/\bv?(\d+)\.(\d+)\.(\d+)\b/);
  if (!match) {
    return null;
  }
  return match.slice(1).map((part) => Number.parseInt(part, 10));
}

function formatNodeVersion(version) {
  return version.join(".");
}

function compareNodeVersion(left, right) {
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) {
      return left[index] - right[index];
    }
  }
  return 0;
}

function nodeRuntimeDiagnostic(versionText) {
  const version = parseNodeVersion(versionText);
  if (!version) {
    return `node returned an unrecognized version \`${versionText.trim()}\``;
  }
  if (version[0] > SUPPORTED_NODE_MAJOR) {
    return `node ${formatNodeVersion(version)} is outside the supported range; Maverick requires ${NODE_RUNTIME_REQUIREMENT}`;
  }
  if (version[0] < SUPPORTED_NODE_MAJOR || compareNodeVersion(version, MINIMUM_NODE_VERSION) < 0) {
    return `node ${formatNodeVersion(version)} is too old; Maverick requires ${NODE_RUNTIME_REQUIREMENT}`;
  }
  return null;
}

const diagnostic = nodeRuntimeDiagnostic(process.version);
if (diagnostic) {
  console.error(diagnostic);
  process.exit(1);
}
