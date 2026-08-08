#!/usr/bin/env node

import {
  APP_ROOT,
  assertInstalledCompositors,
  assertLicenseFiles,
  inspectSupplyChain,
  loadSupplyChainInputs,
} from "./supply-chain-lib.mjs";

const inputs = await loadSupplyChainInputs();
const result = inspectSupplyChain(inputs);
result.errors.push(...(await assertLicenseFiles(APP_ROOT, inputs.policy)));
result.errors.push(...(await assertInstalledCompositors(APP_ROOT, inputs.compositorInventory)));

if (result.errors.length > 0) {
  console.error("Video Studio supply-chain policy failed:");
  for (const error of result.errors) {
    console.error(`- ${error}`);
  }
  process.exit(1);
}

console.log(
  `Video Studio supply-chain policy passed: ${result.components.length} locked packages, Remotion ${inputs.policy.remotion.approved_version}, release redistribution remains blocked.`,
);
