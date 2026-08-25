import {
  cleanFragment,
  displayLocation,
  displayTarget,
  executableName,
  gitSubcommand,
  positionalArguments,
  quoteFragment,
  readTargets,
  ripgrepArguments,
  shellCommandSegments,
  stripCommandPrefixes,
} from "./shellCommandParsing";
import { labelForStatus, statusLabels, type StatusLabels, type ToolActivityStatus } from "./toolActivityStatus";

type CommandPresentation = {
  labels: StatusLabels;
  priority: number;
};

const MAX_LABEL_LENGTH = 112;

export function shellCommandActivityLabel(command: string, status: ToolActivityStatus): string {
  const segments = shellCommandSegments(command);
  const presentations = segments
    .map(commandPresentation)
    .filter((item): item is CommandPresentation => item !== null)
    .sort((left, right) => right.priority - left.priority);
  const selected = presentations[0] || genericCommandPresentation([]);
  return boundLabel(labelForStatus(status, selected.labels));
}

function commandPresentation(rawTokens: string[]): CommandPresentation | null {
  const tokens = stripCommandPrefixes(rawTokens);
  if (!tokens.length) return null;
  const executable = executableName(tokens[0]);
  const lowerTokens = tokens.map((token) => token.toLowerCase());
  const joined = lowerTokens.join(" ");

  if (isTestCommand(executable, lowerTokens, joined)) {
    const target = testTarget(tokens);
    const suffix = target ? ` for ${target}` : "";
    return presentation(100, `Running tests${suffix}`, `Ran tests${suffix}`, `Tests failed${suffix}`, `Ready to run tests${suffix}`);
  }
  if (isBuildCommand(executable, lowerTokens, joined)) {
    return presentation(95, "Building project", "Built project", "Build failed", "Ready to build project");
  }
  if (isTypecheckCommand(executable, lowerTokens, joined)) {
    return presentation(92, "Checking types", "Checked types", "Type check failed", "Ready to check types");
  }
  if (isLintCommand(executable, lowerTokens, joined)) {
    return presentation(90, "Running lint checks", "Ran lint checks", "Lint checks failed", "Ready to run lint checks");
  }
  if (joined.includes("apply_patch") || executable === "apply_patch") {
    return presentation(88, "Applying file changes", "Applied file changes", "File changes failed", "Ready to apply file changes");
  }
  if (executable === "git") return gitPresentation(tokens);
  if (executable === "rg" || executable === "ripgrep") return ripgrepPresentation(tokens);
  if (executable === "find") return findPresentation(tokens);
  if (executable === "ls") return listingPresentation(tokens);
  if (executable === "pwd") {
    return presentation(62, "Checking working directory", "Checked working directory", "Working directory check failed", "Ready to check working directory");
  }
  if (["cat", "head", "tail", "nl", "sed"].includes(executable)) return fileReadPresentation(executable, tokens);
  if (["cp", "mv", "mkdir", "touch", "rm", "rmdir"].includes(executable)) return fileMutationPresentation(executable, tokens);
  if (executable === "test" || executable === "[") return pathCheckPresentation(tokens);
  if (["ps", "pgrep", "lsof"].includes(executable)) {
    return presentation(54, "Inspecting processes", "Inspected processes", "Process inspection failed", "Ready to inspect processes");
  }
  if (executable === "sleep") {
    return presentation(20, "Waiting", "Finished waiting", "Wait interrupted", "Ready to wait");
  }
  return genericCommandPresentation(tokens);
}

function presentation(priority: number, active: string, completed: string, failed: string, waiting: string): CommandPresentation {
  return { labels: statusLabels(active, completed, failed, waiting), priority };
}

function ripgrepPresentation(tokens: string[]): CommandPresentation {
  const { filesOnly, query, targets } = ripgrepArguments(tokens);
  const location = targets.length ? displayLocation(targets) : "workspace";
  if (filesOnly) {
    return presentation(76, `Listing files in ${location}`, `Listed files in ${location}`, `File listing failed in ${location}`, `Ready to list files in ${location}`);
  }
  if (query) {
    const quotedQuery = quoteFragment(query);
    return presentation(80, `Searching for ${quotedQuery} in ${location}`, `Searched for ${quotedQuery} in ${location}`, `Search failed for ${quotedQuery} in ${location}`, `Ready to search for ${quotedQuery} in ${location}`);
  }
  return presentation(76, `Searching files in ${location}`, `Searched files in ${location}`, `File search failed in ${location}`, `Ready to search files in ${location}`);
}

function findPresentation(tokens: string[]): CommandPresentation {
  const root = positionalArguments(tokens.slice(1), new Set(["-maxdepth", "-mindepth", "-type", "-name", "-iname", "-path", "-ipath"]));
  const target = displayTarget(root[0] || ".");
  const nameIndex = tokens.findIndex((token) => token === "-name" || token === "-iname");
  const query = nameIndex >= 0 ? cleanFragment(tokens[nameIndex + 1] || "") : "";
  if (query) {
    const quotedQuery = quoteFragment(query);
    return presentation(78, `Searching for ${quotedQuery} in ${target}`, `Searched for ${quotedQuery} in ${target}`, `Search failed for ${quotedQuery} in ${target}`, `Ready to search for ${quotedQuery} in ${target}`);
  }
  return presentation(74, `Finding files in ${target}`, `Searched files in ${target}`, `File search failed in ${target}`, `Ready to find files in ${target}`);
}

function listingPresentation(tokens: string[]): CommandPresentation {
  const targets = positionalArguments(tokens.slice(1));
  const location = targets.length ? displayLocation(targets) : "workspace";
  return presentation(70, `Listing files in ${location}`, `Listed files in ${location}`, `File listing failed in ${location}`, `Ready to list files in ${location}`);
}

function fileReadPresentation(executable: string, tokens: string[]): CommandPresentation {
  const targets = readTargets(executable, tokens);
  const object = targets.length > 1 ? `${targets.length} files` : displayTarget(targets[0] || "file");
  return presentation(68, `Reading ${object}`, `Read ${object}`, `Failed to read ${object}`, `Ready to read ${object}`);
}

function fileMutationPresentation(executable: string, tokens: string[]): CommandPresentation {
  const targets = positionalArguments(tokens.slice(1), new Set(["-t", "--target-directory"]));
  const lastTarget = displayTarget(targets.at(-1) || "files");
  if (executable === "cp") return presentation(86, `Copying files to ${lastTarget}`, `Copied files to ${lastTarget}`, `Failed to copy files to ${lastTarget}`, `Ready to copy files to ${lastTarget}`);
  if (executable === "mv") return presentation(86, `Moving files to ${lastTarget}`, `Moved files to ${lastTarget}`, `Failed to move files to ${lastTarget}`, `Ready to move files to ${lastTarget}`);
  if (executable === "mkdir") return presentation(86, `Creating ${lastTarget}`, `Created ${lastTarget}`, `Failed to create ${lastTarget}`, `Ready to create ${lastTarget}`);
  if (executable === "rm" || executable === "rmdir") return presentation(86, `Deleting ${lastTarget}`, `Deleted ${lastTarget}`, `Failed to delete ${lastTarget}`, `Ready to delete ${lastTarget}`);
  return presentation(84, `Updating ${lastTarget}`, `Updated ${lastTarget}`, `Failed to update ${lastTarget}`, `Ready to update ${lastTarget}`);
}

function pathCheckPresentation(tokens: string[]): CommandPresentation {
  const targets = positionalArguments(tokens.slice(1));
  const target = displayTarget(targets.at(-1) || "path");
  return presentation(58, `Checking ${target}`, `Checked ${target}`, `Check failed for ${target}`, `Ready to check ${target}`);
}

function gitPresentation(tokens: string[]): CommandPresentation {
  const subcommand = gitSubcommand(tokens);
  if (subcommand === "status") return presentation(82, "Checking repository status", "Checked repository status", "Repository status check failed", "Ready to check repository status");
  if (subcommand === "diff") return presentation(82, "Reviewing repository changes", "Reviewed repository changes", "Repository diff failed", "Ready to review repository changes");
  if (["log", "show", "blame"].includes(subcommand)) return presentation(80, "Reviewing repository history", "Reviewed repository history", "Repository history check failed", "Ready to review repository history");
  if (subcommand === "add") return presentation(84, "Staging repository changes", "Staged repository changes", "Failed to stage repository changes", "Ready to stage repository changes");
  if (subcommand === "commit") return presentation(88, "Committing repository changes", "Committed repository changes", "Commit failed", "Ready to commit repository changes");
  if (subcommand === "push") return presentation(88, "Pushing repository changes", "Pushed repository changes", "Push failed", "Ready to push repository changes");
  return presentation(72, "Inspecting repository", "Inspected repository", "Repository command failed", "Ready to inspect repository");
}

function genericCommandPresentation(tokens: string[]): CommandPresentation {
  const executable = executableName(tokens[0] || "command");
  const displayName = executable === "maverick" ? "Maverick command" : cleanFragment(executable || "command");
  return presentation(10, `Running ${displayName}`, `Ran ${displayName}`, `${capitalize(displayName)} failed`, `Ready to run ${displayName}`);
}

function isTestCommand(executable: string, tokens: string[], joined: string): boolean {
  if (["jest", "mocha", "playwright", "pytest", "vitest"].includes(executable)) return true;
  if (["npm", "pnpm", "yarn", "bun"].includes(executable) && /(^| )(run )?test(?::| |$)/.test(joined)) return true;
  if (["cargo", "dotnet", "go", "gradle", "mvn"].includes(executable) && tokens.includes("test")) return true;
  if (["make", "ninja"].includes(executable) && tokens.includes("test")) return true;
  if (/^python(?:\d+(?:\.\d+)*)?$/.test(executable) && (joined.includes(" -m pytest") || joined.includes(" -m unittest"))) return true;
  return tokens.some((token) => /(^|\/)(test_[^/]+\.py|[^/]+\.(?:spec|test)\.[cm]?[jt]sx?)$/.test(token) || /(^|\/)(?:test_suite|smoke_[^/]+)\.py$/.test(token));
}

function isBuildCommand(executable: string, tokens: string[], joined: string): boolean {
  if (["make", "ninja"].includes(executable)) return true;
  if (["npm", "pnpm", "yarn", "bun"].includes(executable) && /(^| )(run )?build(?::| |$)/.test(joined)) return true;
  return ["cargo", "dotnet", "go"].includes(executable) && tokens.includes("build");
}

function isTypecheckCommand(executable: string, tokens: string[], joined: string): boolean {
  return executable === "tsc" || joined.includes(" typecheck") || joined.includes(" type-check") || (executable === "mypy" || executable === "pyright") || tokens.includes("--noemit");
}

function isLintCommand(executable: string, _tokens: string[], joined: string): boolean {
  return ["eslint", "ruff", "pylint"].includes(executable) || /(^| )(run )?lint(?::| |$)/.test(joined);
}

function testTarget(tokens: string[]): string {
  const target = tokens.find((token, index) => index > 0 && !token.startsWith("-") && /(?:^|\/)(?:test_[^/]+\.py|[^/]+\.(?:spec|test)\.[cm]?[jt]sx?)$/.test(token));
  return target ? displayTarget(target) : "";
}

function boundLabel(value: string): string {
  if (value.length <= MAX_LABEL_LENGTH) return value;
  return `${value.slice(0, MAX_LABEL_LENGTH - 1).trimEnd()}…`;
}

function capitalize(value: string): string {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : value;
}
