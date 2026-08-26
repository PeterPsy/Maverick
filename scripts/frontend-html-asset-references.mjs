import { readFileSync } from "node:fs";
import { posix, resolve } from "node:path";

const STATIC_LINK_RELATIONS = new Set([
  "apple-touch-icon",
  "icon",
  "manifest",
  "mask-icon",
  "modulepreload",
  "preload",
  "stylesheet",
]);

function htmlTags(source) {
  const tags = [];
  const lowerSource = source.toLowerCase();
  let position = 0;
  while (position < source.length) {
    const tagStart = source.indexOf("<", position);
    if (tagStart < 0) break;
    if (source.startsWith("<!--", tagStart)) {
      const commentEnd = source.indexOf("-->", tagStart + 4);
      position = commentEnd < 0 ? source.length : commentEnd + 3;
      continue;
    }
    let cursor = tagStart + 1;
    while (/\s/.test(source[cursor] || "")) cursor += 1;
    if (source[cursor] === "/" || source[cursor] === "!" || source[cursor] === "?") {
      position = tagStart + 1;
      continue;
    }
    const nameMatch = /^[A-Za-z][A-Za-z0-9:-]*/.exec(source.slice(cursor));
    if (!nameMatch) {
      position = tagStart + 1;
      continue;
    }
    const tagName = nameMatch[0].toLowerCase();
    cursor += nameMatch[0].length;
    const attributesStart = cursor;
    let quote = "";
    while (cursor < source.length) {
      const character = source[cursor];
      if (quote) {
        if (character === quote) quote = "";
      } else if (character === '"' || character === "'") {
        quote = character;
      } else if (character === ">") {
        break;
      }
      cursor += 1;
    }
    if (cursor >= source.length) break;
    const attributes = new Map();
    const attributeSource = source.slice(attributesStart, cursor);
    const attributePattern = /([^\s"'<>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
    for (const match of attributeSource.matchAll(attributePattern)) {
      attributes.set(match[1].toLowerCase(), match[2] ?? match[3] ?? match[4] ?? "");
    }
    tags.push({ attributes, name: tagName });
    position = cursor + 1;
    if (tagName === "script" || tagName === "style") {
      const closeStart = lowerSource.indexOf(`</${tagName}`, position);
      if (closeStart >= 0) position = closeStart;
    }
  }
  return tags;
}

function srcsetReferences(value) {
  if (value.trim().toLowerCase().startsWith("data:")) return [];
  return value
    .split(",")
    .map((candidate) => candidate.trim().split(/\s+/, 1)[0])
    .filter(Boolean);
}

function staticReferencesForTag({ attributes, name }) {
  const references = [];
  const add = (attribute) => {
    const value = attributes.get(attribute);
    if (value) references.push(value);
  };
  if (["audio", "embed", "img", "input", "script", "source", "track", "video"].includes(name)) {
    add("src");
  }
  if (name === "img" || name === "source") {
    references.push(...srcsetReferences(attributes.get("srcset") || ""));
  }
  if (name === "video") add("poster");
  if (name === "object") add("data");
  if (name === "image" || name === "use") add("href");
  if (name === "link") {
    const relations = (attributes.get("rel") || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (relations.some((relation) => STATIC_LINK_RELATIONS.has(relation))) add("href");
    references.push(...srcsetReferences(attributes.get("imagesrcset") || ""));
  }
  return references;
}

function artifactPathForHtmlReference({ base, entrypoint, reference }) {
  const value = reference.trim();
  if (!value || value.startsWith("#") || value.startsWith("?") || value.startsWith("//")) return null;
  const withoutSuffix = value.split(/[?#]/, 1)[0];
  if (!withoutSuffix) return null;
  let candidate;
  if (typeof base === "string" && base.startsWith("/") && withoutSuffix.startsWith(base)) {
    candidate = withoutSuffix.slice(base.length);
  } else if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(withoutSuffix)) {
    return null;
  } else if (withoutSuffix.startsWith("/")) {
    candidate = withoutSuffix.slice(1);
  } else {
    candidate = posix.join(posix.dirname(entrypoint), withoutSuffix);
  }
  try {
    candidate = decodeURIComponent(candidate);
  } catch {
    return candidate;
  }
  const normalized = posix.normalize(candidate);
  const escapedArtifact = !normalized || normalized === "." || normalized === ".." || normalized.startsWith("../");
  return escapedArtifact ? candidate : normalized;
}

export function validateHtmlAssetReferences({ base, entrypoints, outDir, paths }) {
  const availablePaths = new Set(paths);
  const missing = [];
  for (const entrypoint of entrypoints) {
    const source = readFileSync(resolve(outDir, entrypoint), "utf8");
    for (const tag of htmlTags(source)) {
      for (const reference of staticReferencesForTag(tag)) {
        const artifactPath = artifactPathForHtmlReference({ base, entrypoint, reference });
        if (artifactPath && !availablePaths.has(artifactPath)) {
          missing.push({ artifactPath, entrypoint, reference });
        }
      }
    }
  }
  if (missing.length > 0) {
    const { artifactPath, entrypoint, reference } = missing.sort((left, right) => (
      `${left.entrypoint}\0${left.reference}`.localeCompare(`${right.entrypoint}\0${right.reference}`)
    ))[0];
    throw new Error(
      `Maverick HTML asset reference is missing from build output: ${entrypoint} -> ${reference} (${artifactPath})`,
    );
  }
}
