const DEFAULT_TTS_CHUNK_CHARS = 450;
const INITIAL_TTS_CHUNK_CHARS = 120;
const MIN_RETRY_TTS_CHUNK_CHARS = 120;
const TTS_WORD_RE = /[A-Za-zÀ-ÿ']+/g;

const ITALIAN_TTS_MARKERS = new Set([
  "abbiamo",
  "adesso",
  "aiutarti",
  "anche",
  "applicato",
  "audio",
  "cambiato",
  "che",
  "chiamata",
  "come",
  "con",
  "controlla",
  "corretta",
  "correttamente",
  "della",
  "delle",
  "degli",
  "dopo",
  "fatto",
  "funziona",
  "funzionano",
  "iniziale",
  "italiana",
  "italiano",
  "la",
  "latenza",
  "lettura",
  "messaggio",
  "modello",
  "nel",
  "non",
  "ora",
  "parte",
  "partire",
  "passate",
  "per",
  "processi",
  "pronuncia",
  "questa",
  "questo",
  "reale",
  "ridotto",
  "risponde",
  "risposta",
  "rotta",
  "solo",
  "sono",
  "subito",
  "testo",
  "una",
  "usare",
  "verificato",
  "verifiche",
  "voce",
]);

const ITALIAN_STRONG_TTS_MARKERS = new Set([
  "adesso",
  "aiutarti",
  "ciao",
  "corretta",
  "fatto",
  "funziona",
  "grazie",
  "italiana",
  "italiano",
  "latenza",
  "lettura",
  "pronuncia",
  "subito",
]);

const ENGLISH_TTS_MARKERS = new Set([
  "about",
  "and",
  "because",
  "can",
  "done",
  "for",
  "from",
  "hello",
  "message",
  "not",
  "response",
  "speech",
  "that",
  "the",
  "this",
  "voice",
  "with",
  "you",
]);

const MARKDOWN_STRONG_ASTERISK = /(^|[^\w*])\*\*([^\s*](?:[\s\S]*?[^\s*])?)\*\*(?=$|[^\w*])/g;
const MARKDOWN_EMPHASIS_ASTERISK = /(^|[^\w*])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?=$|[^\w*])/g;
const MARKDOWN_STRIKE = /(^|[^\w~])~~([^\s~](?:[\s\S]*?[^\s~])?)~~(?=$|[^\w~])/g;
const MARKDOWN_STRONG_UNDERSCORE =
  /(^|[^\w_])__(?!(?:init|name|main|file|doc|class|module|dict|repr|str|call|enter|exit|iter|next|len|new|del)__)([^\s_](?:[\s\S]*?[^\s_])?)__(?=$|[^\w_])/g;
const MARKDOWN_EMPHASIS_UNDERSCORE = /(^|[^\w_])_(?!_)([^\s_](?:[^_\n]*?[^\s_])?)_(?!_)(?=$|[^\w_])/g;

export function speechLanguageHint(text: string): string {
  const normalized = text.toLowerCase();
  const tokens = new Set(
    Array.from(normalized.matchAll(TTS_WORD_RE), ([token]) => token.replace(/^'+|'+$/g, "")).filter((token) => token.length > 1),
  );
  let italianScore = 0;
  let englishScore = 0;
  for (const token of tokens) {
    if (ITALIAN_TTS_MARKERS.has(token)) {
      italianScore += 1;
    }
    if (ENGLISH_TTS_MARKERS.has(token)) {
      englishScore += 1;
    }
  }
  if (/[àèéìòù]/.test(normalized)) {
    italianScore += 2;
  }
  if (englishScore === 0 && Array.from(tokens).some((token) => ITALIAN_STRONG_TTS_MARKERS.has(token))) {
    return "it";
  }
  return italianScore >= 2 && italianScore > englishScore ? "it" : "";
}

export function speechChunks(text: string, maxTextChars = 0): string[] {
  const limit = maxTextChars > 0 ? Math.min(maxTextChars, DEFAULT_TTS_CHUNK_CHARS) : DEFAULT_TTS_CHUNK_CHARS;
  const initialLimit = Math.min(limit, INITIAL_TTS_CHUNK_CHARS);
  const normalized = text.trim();
  if (!normalized) {
    return [];
  }
  if (normalized.length <= initialLimit) {
    return [normalized];
  }
  const [initialChunk, remaining] = splitInitialSpeechChunk(normalized, initialLimit);
  return [initialChunk, ...speechChunksWithLimit(remaining, limit)].filter(Boolean);
}

function speechChunksWithLimit(text: string, limit: number): string[] {
  const chunks: string[] = [];
  let current = "";
  for (const piece of speechPieces(text)) {
    const next = current ? `${current} ${piece}` : piece;
    if (next.length <= limit) {
      current = next;
      continue;
    }
    if (current) {
      chunks.push(current);
      current = "";
    }
    chunks.push(...hardSplitSpeechPiece(piece, limit));
  }
  if (current) {
    chunks.push(current);
  }
  return chunks;
}

function splitInitialSpeechChunk(text: string, limit: number): [string, string] {
  const prefix = text.slice(0, limit);
  const sentenceEnds = Array.from(prefix.matchAll(/[.!?](?=\s|$)/g));
  const sentenceSplit = sentenceEnds.at(-1)?.index;
  const wordSplit = text.lastIndexOf(" ", limit);
  const splitAt = typeof sentenceSplit === "number" ? sentenceSplit + 1 : wordSplit > 0 ? wordSplit : limit;
  return [text.slice(0, splitAt).trim(), text.slice(splitAt).trim()];
}

function speechPieces(text: string): string[] {
  return text
    .replace(/\n{2,}/g, ". ")
    .split(/(?<=[.!?])\s+/)
    .map((piece) => piece.trim())
    .filter(Boolean);
}

function hardSplitSpeechPiece(piece: string, limit: number): string[] {
  const chunks: string[] = [];
  let remaining = piece.trim();
  while (remaining.length > limit) {
    const wordSplit = remaining.lastIndexOf(" ", limit);
    const splitAt = wordSplit > 0 ? wordSplit : limit;
    chunks.push(remaining.slice(0, splitAt).trim());
    remaining = remaining.slice(splitAt).trim();
  }
  if (remaining) {
    chunks.push(remaining);
  }
  return chunks;
}

export function retrySpeechChunks(text: string): string[] {
  if (text.length <= MIN_RETRY_TTS_CHUNK_CHARS) {
    return [text];
  }
  const midpoint = Math.floor(text.length / 2);
  const before = text.lastIndexOf(" ", midpoint);
  const after = text.indexOf(" ", midpoint);
  const splitAt = before >= MIN_RETRY_TTS_CHUNK_CHARS ? before : after > 0 ? after : midpoint;
  const left = text.slice(0, splitAt).trim();
  const right = text.slice(splitAt).trim();
  return [left, right].filter(Boolean);
}

export function isSplittableSynthesisError(error: unknown): boolean {
  const message = error instanceof Error ? error.message.toLowerCase() : "";
  return (
    message.includes("synthesized audio exceeds") ||
    message.includes("response size limit") ||
    message.includes("text must contain at most") ||
    message.includes("max_text_chars")
  );
}

export function speechTextFromMarkdown(content: string) {
  return withoutFencedCodeBlocks(content.replace(/\r\n?/g, "\n"))
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\[ref:[^\]]+\]/g, "")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/^\s*\|?[\s:-]+\|[\s|:-]*$/gm, "")
    .replace(/\|/g, " ")
    .replace(MARKDOWN_STRONG_ASTERISK, "$1$2")
    .replace(MARKDOWN_EMPHASIS_ASTERISK, "$1$2")
    .replace(MARKDOWN_STRIKE, "$1$2")
    .replace(MARKDOWN_STRONG_UNDERSCORE, "$1$2")
    .replace(MARKDOWN_EMPHASIS_UNDERSCORE, "$1$2")
    .replace(/[ \t]+/g, " ")
    .replace(/^[ \t]+|[ \t]+$/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function speechLanguageTextFromMarkdown(content: string): string {
  const withoutFencedCode = withoutFencedCodeBlocks(content.replace(/\r\n?/g, "\n"));
  return speechTextFromMarkdown(withoutFencedCode.replace(/`[^`\n]+`/g, " "));
}

function withoutFencedCodeBlocks(content: string): string {
  return content.replace(/```[^\n]*\n[\s\S]*?```/g, "\n").replace(/```[\s\S]*?```/g, "\n");
}
