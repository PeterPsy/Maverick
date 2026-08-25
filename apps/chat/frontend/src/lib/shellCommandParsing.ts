const MAX_FRAGMENT_LENGTH = 80;
const SHELL_OPERATORS = new Set(["&&", "||", ";", "|"]);
const SHELL_WRAPPERS = new Set(["bash", "dash", "sh", "zsh"]);

export function shellCommandSegments(command: string): string[][] {
  const tokens = tokenizeShell(command);
  const unwrapped = unwrapShellCommand(tokens);
  const segments: string[][] = [];
  let current: string[] = [];
  for (const token of unwrapped) {
    if (SHELL_OPERATORS.has(token)) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push(token);
    }
  }
  if (current.length) segments.push(current);
  return segments.length ? segments : [unwrapped];
}

export function stripCommandPrefixes(tokens: string[]): string[] {
  const result = [...tokens];
  while (result.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(result[0])) result.shift();
  while (result.length && ["command", "builtin", "nohup", "sudo"].includes(executableName(result[0]))) {
    result.shift();
    while (result[0]?.startsWith("-")) result.shift();
  }
  if (executableName(result[0] || "") === "env") {
    result.shift();
    while (result.length && (result[0].startsWith("-") || /^[A-Za-z_][A-Za-z0-9_]*=/.test(result[0]))) result.shift();
  }
  if (["bunx", "npx", "pnpx"].includes(executableName(result[0] || ""))) {
    result.shift();
    while (result[0]?.startsWith("-")) result.shift();
  }
  return result;
}

export function ripgrepArguments(tokens: string[]): { filesOnly: boolean; query: string; targets: string[] } {
  const optionValues = new Set(["-A", "-B", "-C", "-e", "-f", "-g", "-r", "-t", "-T", "--after-context", "--before-context", "--context", "--encoding", "--engine", "--file", "--glob", "--iglob", "--max-count", "--max-depth", "--regexp", "--replace", "--sort", "--sortr", "--type", "--type-not"]);
  const positional: string[] = [];
  let explicitQuery = "";
  let filesOnly = false;
  for (let index = 1; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token === "--files") {
      filesOnly = true;
      continue;
    }
    if (token === "--") {
      positional.push(...tokens.slice(index + 1));
      break;
    }
    if (optionValues.has(token)) {
      const value = tokens[index + 1] || "";
      if (token === "-e" || token === "--regexp") explicitQuery ||= value;
      index += 1;
      continue;
    }
    if (token.startsWith("-")) continue;
    positional.push(token);
  }
  if (filesOnly) return { filesOnly, query: "", targets: positional };
  const query = explicitQuery || positional.shift() || "";
  return { filesOnly, query: cleanFragment(query), targets: positional };
}

export function positionalArguments(tokens: string[], optionsWithValues = new Set<string>()): string[] {
  const values: string[] = [];
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token === "--") {
      values.push(...tokens.slice(index + 1));
      break;
    }
    if (optionsWithValues.has(token)) {
      index += 1;
      continue;
    }
    if (!token.startsWith("-") && !/^\d+$/.test(token)) values.push(token);
  }
  return values;
}

export function readTargets(executable: string, tokens: string[]): string[] {
  if (executable !== "sed") {
    const optionValues = executable === "head" || executable === "tail" ? new Set(["-c", "-n"]) : new Set<string>();
    return positionalArguments(tokens.slice(1), optionValues);
  }
  const candidates: string[] = [];
  let expressionConsumed = false;
  for (let index = 1; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (token === "-e" || token === "--expression") {
      expressionConsumed = true;
      index += 1;
      continue;
    }
    if (token === "-f" || token === "--file") {
      index += 1;
      continue;
    }
    if (token.startsWith("-")) continue;
    if (!expressionConsumed) {
      expressionConsumed = true;
      continue;
    }
    candidates.push(token);
  }
  return candidates;
}

export function gitSubcommand(tokens: string[]): string {
  for (let index = 1; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (["-C", "--git-dir", "--work-tree", "-c"].includes(token)) {
      index += 1;
      continue;
    }
    if (!token.startsWith("-")) return token.toLowerCase();
  }
  return "";
}

export function displayLocation(targets: string[]): string {
  if (targets.length === 1) return displayTarget(targets[0]);
  return `${targets.length} locations`;
}

export function displayTarget(value: string): string {
  let target = normalizeFragment(value || "workspace");
  if (!target || target === ".") return "workspace";
  const repositoryMarker = target.match(/\/(apps|core|docs|tests|workspaces)\/.+$/)?.[0];
  if (repositoryMarker) target = repositoryMarker.slice(1);
  const segments = target.split("/").filter(Boolean);
  if (target.length > MAX_FRAGMENT_LENGTH && segments.length > 5) target = `…/${segments.slice(-5).join("/")}`;
  return cleanFragment(target);
}

export function quoteFragment(value: string): string {
  return `“${cleanFragment(value)}”`;
}

export function cleanFragment(value: string): string {
  const normalized = normalizeFragment(value);
  if (normalized.length <= MAX_FRAGMENT_LENGTH) return normalized;
  return `${normalized.slice(0, MAX_FRAGMENT_LENGTH - 1).trimEnd()}…`;
}

export function executableName(value: string): string {
  return String(value || "").split("/").at(-1)?.toLowerCase() || "";
}

function unwrapShellCommand(tokens: string[]): string[] {
  if (!tokens.length || !SHELL_WRAPPERS.has(executableName(tokens[0]))) return tokens;
  const commandFlagIndex = tokens.findIndex((token, index) => index > 0 && /^-[a-z]*c[a-z]*$/i.test(token));
  const script = commandFlagIndex >= 0 ? tokens[commandFlagIndex + 1] : "";
  return script ? tokenizeShell(script) : tokens;
}

function tokenizeShell(command: string): string[] {
  const tokens: string[] = [];
  let current = "";
  let quote: "'" | '"' | null = null;
  let escaped = false;
  const pushCurrent = () => {
    if (current) tokens.push(current);
    current = "";
  };
  for (let index = 0; index < command.length; index += 1) {
    const char = command[index];
    if (escaped) {
      current += char;
      escaped = false;
      continue;
    }
    if (char === "\\" && quote !== "'") {
      escaped = true;
      continue;
    }
    if (quote) {
      if (char === quote) quote = null;
      else current += char;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      continue;
    }
    if (char === "\n" || char === ";" || char === "|" || char === "&") {
      pushCurrent();
      if (char === "\n" || char === ";") tokens.push(";");
      else if (command[index + 1] === char) {
        tokens.push(`${char}${char}`);
        index += 1;
      } else tokens.push(char);
      continue;
    }
    if (/\s/.test(char)) pushCurrent();
    else current += char;
  }
  if (escaped) current += "\\";
  pushCurrent();
  return tokens;
}

function normalizeFragment(value: string): string {
  return String(value || "").replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
}
