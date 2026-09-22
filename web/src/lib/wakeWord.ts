/** Pure wake phrase matching, independent of browser audio. */
export const DEFAULT_WAKE_WORD = "Hey JARVIS";

export function normalizeWakeWord(value?: string): string {
  return value?.trim().replace(/\s+/g, " ") || DEFAULT_WAKE_WORD;
}

function isDefaultWakeWord(value: string): boolean {
  return normalizeWakeWord(value).toLowerCase() === DEFAULT_WAKE_WORD.toLowerCase();
}

function customWakePattern(value: string, leadingOnly = false): RegExp {
  const phrase = normalizeWakeWord(value);
  const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  // Chinese/Japanese transcripts may join the wake phrase and command.
  // Other phrases need word boundaries to avoid matching inside words.
  const unspaced = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u;
  const chars = Array.from(phrase);
  const left = unspaced.test(chars[0]) ? "" : "(?<![\\p{L}\\p{N}_])";
  const right = unspaced.test(chars[chars.length - 1]) ? "" : "(?![\\p{L}\\p{N}_])";
  return new RegExp(
    (leadingOnly ? "^\\s*" : left) + escaped + right
      + (leadingOnly ? "[\\s,.:!?;，。！？、：；—–-]*" : ""),
    "iu",
  );
}

// --- Fuzzy wake-word detection ----------------------------------------------
// Whisper often mishears "jarvis" as jorvis / jervis / jurvis / charvis /
// jarvus / javis / jarvises / yarvis / harvis ... We accept any token that
// is close enough by either:
//   1. shape regex:  j → vowel → optional r → v → vowel → s
//   2. Levenshtein distance ≤ 2 from "jarvis"
//   3. starts with a soft "j/y/h/ch" cluster + jarvis-ish tail
// Plus the canonical phrases (hey jarvis, ok jarvis, etc).
const WAKE_SHAPE_RE = /\b(?:hey|ok|okay|yo|hi|ay)?\s*(?:[jyhc]h?|ch)[aeiouy]+r?[vb][aeiouy]+s+(?:es|is)?\b/i;
const WAKE_STRICT_RE = /\b(?:hey|ok|okay|yo|hi|ay)?\s*j\.?a\.?r\.?v\.?i\.?s\.?\b/i;

function levenshtein(a: string, b: string): number {
  a = a.toLowerCase(); b = b.toLowerCase();
  if (a === b) return 0;
  const m = a.length, n = b.length;
  if (!m) return n; if (!n) return m;
  const dp: number[] = Array(n + 1);
  for (let j = 0; j <= n; j++) dp[j] = j;
  for (let i = 1; i <= m; i++) {
    let prev = dp[0]; dp[0] = i;
    for (let j = 1; j <= n; j++) {
      const tmp = dp[j];
      dp[j] = a[i - 1] === b[j - 1]
        ? prev
        : 1 + Math.min(prev, dp[j], dp[j - 1]);
      prev = tmp;
    }
  }
  return dp[n];
}

function isJarvisLike(token: string): boolean {
  const t = token.toLowerCase().replace(/[^a-z]/g, "");
  if (!t || t.length < 4 || t.length > 9) return false;
  // Common phonetic family
  if (/^[jyhc]h?[aeiouy]+r?[vb][aeiouy]+s+(?:es|is)?$/.test(t)) return true;
  // Edit distance from canonical
  return levenshtein(t, "jarvis") <= 2;
}

export function detectWake(text: string, wakeWord = DEFAULT_WAKE_WORD): boolean {
  if (!isDefaultWakeWord(wakeWord)) return customWakePattern(wakeWord).test(text);
  if (WAKE_STRICT_RE.test(text) || WAKE_SHAPE_RE.test(text)) return true;
  // Token-level Levenshtein fallback — catches odd Whisper outputs like
  // "Jarves," "Jervis," "Charvis," "Yarvis," etc.
  for (const tok of text.split(/[\s,.\!\?\-:;'"]+/)) {
    if (isJarvisLike(tok)) return true;
  }
  return false;
}

export function stripWakeWord(text: string, wakeWord = DEFAULT_WAKE_WORD): string {
  if (!isDefaultWakeWord(wakeWord)) {
    return text.replace(customWakePattern(wakeWord, true), "").trim();
  }
  // Strip strict match first
  let out = text.replace(/^\s*(?:hey|ok|okay|yo|hi|ay)?\s*j\.?a\.?r\.?v\.?i\.?s\.?[\s,.\-:!?]*/i, "");
  if (out !== text) return out.trim();
  // Strip fuzzy first-token if Jarvis-like
  const m = out.match(/^\s*(\S+)[\s,.\-:!?]*/);
  if (m && isJarvisLike(m[1])) {
    out = out.slice(m[0].length);
    // Also peel a leading filler like "hey/ok"
    const m2 = out.match(/^\s*(\S+)[\s,.\-:!?]*/);
    if (m2 && /^(?:hey|ok|okay|yo|hi|ay)$/i.test(m2[1])) {
      out = out.slice(m2[0].length);
    }
  } else {
    // Strip leading filler then fuzzy
    const mf = out.match(/^\s*(hey|ok|okay|yo|hi|ay)\s+(\S+)[\s,.\-:!?]*/i);
    if (mf && isJarvisLike(mf[2])) out = out.slice(mf[0].length);
  }
  return out.trim();
}
