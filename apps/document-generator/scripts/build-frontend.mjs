import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = resolve(appRoot, "frontend/src");
const distRoot = resolve(appRoot, "frontend/dist");

rmSync(distRoot, { force: true, recursive: true });
mkdirSync(distRoot, { recursive: true });
cpSync(sourceRoot, distRoot, { recursive: true });
