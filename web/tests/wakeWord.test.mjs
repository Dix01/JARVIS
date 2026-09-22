import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Exercise the same pure TypeScript matcher used by the microphone without
// requiring a browser or a second test framework (works with Node 18+).
const source = readFileSync(new URL("../src/lib/wakeWord.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
});
const { detectWake, stripWakeWord, normalizeWakeWord } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

test("default keeps canonical and fuzzy JARVIS wake phrases", () => {
  for (const phrase of ["Hey JARVIS", "Jarvis", "J.A.R.V.I.S.", "Hey Jervis", "Charvis"]) {
    assert.equal(detectWake(`${phrase}, open the browser`), true, phrase);
    assert.equal(stripWakeWord(`${phrase}, open the browser`), "open the browser", phrase);
    assert.equal(stripWakeWord(phrase), "", phrase);
  }
  assert.equal(detectWake("open the browser"), false);
});

test("custom phrase replaces JARVIS and matches case and whitespace variations", () => {
  assert.equal(detectWake("HEY   FRIDAY, open the browser", "Hey Friday"), true);
  assert.equal(stripWakeWord("HEY   FRIDAY, open the browser", "Hey Friday"), "open the browser");
  assert.equal(stripWakeWord("Hey Friday!", "Hey Friday"), "");
  assert.equal(detectWake("Hey JARVIS, open the browser", "Hey Friday"), false);
  assert.equal(detectWake("Friday, open the browser", "Hey Friday"), false);
  assert.equal(detectWake("Hey Fridays", "Hey Friday"), false);
  assert.equal(detectWake("xhey friday", "Hey Friday"), false);
  assert.equal(detectWake("Hey Fridaz", "Hey Friday"), false);
});

test("custom phrases are literal, including regular expression characters", () => {
  assert.equal(detectWake("Assistant+, hello", "Assistant+"), true);
  assert.equal(stripWakeWord("Assistant+, hello", "Assistant+"), "hello");
  assert.equal(detectWake("Assistant hello", "Assistant+"), false);
  assert.equal(detectWake("any speech", ".*"), false);
  assert.equal(detectWake("A[1], hello", "A[1]"), true);
});

test("Unicode phrases and punctuation are retained correctly", () => {
  assert.equal(detectWake("贾维斯，打开浏览器", "贾维斯"), true);
  assert.equal(stripWakeWord("贾维斯，打开浏览器", "贾维斯"), "打开浏览器");
  assert.equal(stripWakeWord("贾维斯打开浏览器", "贾维斯"), "打开浏览器");
  assert.equal(stripWakeWord("贾维斯！", "贾维斯"), "");
  assert.equal(detectWake("HÉ ASSISTANT, bonjour", "Hé Assistant"), true);
  assert.equal(detectWake("préassistant", "assistant"), false);
});

test("follow-ups stay intact; wake phrases inside a sentence are not stripped", () => {
  assert.equal(stripWakeWord("and open my notes", "Hey Friday"), "and open my notes");
  assert.equal(detectWake("please, Hey Friday, help", "Hey Friday"), true);
  assert.equal(stripWakeWord("please, Hey Friday, help", "Hey Friday"), "please, Hey Friday, help");
});

test("configuration normalization preserves the default fallback", () => {
  assert.equal(normalizeWakeWord(undefined), "Hey JARVIS");
  assert.equal(normalizeWakeWord("   "), "Hey JARVIS");
  assert.equal(normalizeWakeWord("  Hey  Friday  "), "Hey Friday");
  assert.equal(detectWake("Jervis", " hey  jarvis "), true);
});
