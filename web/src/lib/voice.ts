/**
 * Browser-side voice: SpeechSynthesis (TTS) + SpeechRecognition (STT).
 * Works without any backend mic — uses the browser microphone if present.
 * Degrades silently if the API is missing.
 */
import { useStore, type VoiceProfile } from "./store";

// --- TTS ---
const SYNTH = typeof window !== "undefined" ? window.speechSynthesis : null;

const JARVIS_VOICE_MATCHERS = [
  /microsoft ryan.*(?:online|natural)|ryan.*(?:online|natural)/i,
  /en-GB-Ryan/i,
  /microsoft george/i,
  /google uk english male/i,
  /\bDaniel\b/i,
  /\bOliver\b/i,
  /\bGeorge\b/i,
  /\bArthur\b/i,
  /\bRyan\b/i,
];

const LOWER_CONFIDENCE_VOICES = /female|hazel|susan|sonia|libby|zira|aria|jenny/i;

let cachedVoice: SpeechSynthesisVoice | null = null;
let activeAudio: HTMLAudioElement | null = null;
let activeAudioUrl: string | null = null;

// ── Streaming TTS queue ────────────────────────────────────────────────────
// Sentences are detected as they stream in. Each sentence is fetched
// independently from /api/tts and queued. Audio plays in order so the
// listener hears JARVIS in real time, not after the full text finishes.
//
// HARD GUARANTEE — only ONE audio source plays at a time:
//   • single shared HTMLAudioElement `playerAudio` (browser cannot play two
//     clips on one element). All streaming clips run through it serially.
//   • every queue mutation and every clip start gates on `streamGeneration`.
//     A cancel bumps the generation; any in-flight fetch / scheduled
//     advance from the previous generation drops on sight.
//   • cancel pauses the player FIRST, then clears the queue, then nukes any
//     legacy speakWithServerTts audio AND browser-SpeechSynthesis voice.
type QueuedClip = { url: string };
const ttsQueue: QueuedClip[] = [];
let ttsPlaying = false;
let activeUrl: string | null = null;
const playerAudio: HTMLAudioElement | null =
  typeof Audio !== "undefined" ? new Audio() : null;
if (playerAudio) {
  playerAudio.preload = "auto";
  // Single global listeners — re-attaching per clip caused leak + race.
  playerAudio.addEventListener("ended", () => handleClipFinished("ended"));
  playerAudio.addEventListener("error", () => handleClipFinished("error"));
}
const streamState = { id: "", spokenChars: 0 };
let pendingFetches = 0;
let streamGeneration = 0;   // bumped on cancel — stale fetches compare this
let activeGeneration = 0;   // the generation that owns the currently-playing clip
function voiceScore(voice: SpeechSynthesisVoice): number {
  const label = `${voice.name} ${voice.lang}`;
  const matcherIndex = JARVIS_VOICE_MATCHERS.findIndex((re) => re.test(label));
  let score = matcherIndex >= 0 ? 120 - matcherIndex * 10 : 0;
  if (/en-GB/i.test(label)) score += 35;
  if (/(?:natural|online|neural)/i.test(label)) score += 25;
  if (LOWER_CONFIDENCE_VOICES.test(label)) score -= 20;
  if (/^en/i.test(voice.lang)) score += 5;
  return score;
}

function voiceTier(voice: SpeechSynthesisVoice | null): VoiceProfile["tier"] {
  if (!voice) return "offline";
  const label = `${voice.name} ${voice.lang}`;
  if (/ryan|george|daniel|oliver|arthur|google uk english male/i.test(label)) return "cinematic";
  if (/en-GB|UK English|British/i.test(label)) return "british";
  return "fallback";
}

function publishVoiceProfile(voice: SpeechSynthesisVoice | null) {
  useStore.getState().setVoiceProfile(
    voice
      ? { name: voice.name, lang: voice.lang, tier: voiceTier(voice) }
      : { name: "No browser TTS voice", lang: "offline", tier: "offline" }
  );
}

function pickVoice(): SpeechSynthesisVoice | null {
  if (!SYNTH) {
    publishVoiceProfile(null);
    return null;
  }
  if (cachedVoice) return cachedVoice;
  const voices = SYNTH.getVoices();
  const ranked = [...voices].sort((a, b) => voiceScore(b) - voiceScore(a));
  const prefer = ranked.find((v) => voiceScore(v) > 0)
              || voices.find((v) => v.lang === "en-GB")
              || voices.find((v) => v.lang.startsWith("en"))
              || voices[0]
              || null;
  cachedVoice = prefer ?? null;
  publishVoiceProfile(cachedVoice);
  return cachedVoice;
}

if (typeof window !== "undefined" && SYNTH) {
  SYNTH.onvoiceschanged = () => { cachedVoice = null; pickVoice(); };
}

export function refreshVoiceProfile(): void {
  void refreshServerVoiceProfile();
  pickVoice();
}

export function currentVoiceProfile(): VoiceProfile | null {
  const voice = pickVoice();
  return voice ? { name: voice.name, lang: voice.lang, tier: voiceTier(voice) } : null;
}

async function refreshServerVoiceProfile(): Promise<void> {
  try {
    const resp = await fetch("/api/tts/status");
    if (!resp.ok) return;
    const status = await resp.json();
    if (status?.available) {
      useStore.getState().setVoiceProfile({
        name: status.label || "Microsoft Ryan Neural",
        lang: status.lang || "en-GB",
        tier: "cinematic",
      });
    }
  } catch {
    // browser voices remain the fallback
  }
}

function cleanSpeechText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " code block ")
    .replace(/[*_`#>~]/g, "")
    .replace(/\[(.*?)\]\(.*?\)/g, "$1")
    .trim();
}

function stopServerAudio() {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio = null;
  }
  if (activeAudioUrl) {
    URL.revokeObjectURL(activeAudioUrl);
    activeAudioUrl = null;
  }
}

async function speakWithServerTts(clean: string): Promise<boolean> {
  try {
    console.log("[TTS] requesting server TTS…");
    const resp = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean }),
    });
    console.log("[TTS] server response:", resp.status, resp.headers.get("content-type"));
    if (!resp.ok) {
      console.warn("[TTS] server returned", resp.status);
      return false;
    }
    const blob = await resp.blob();
    console.log("[TTS] audio blob:", blob.size, "bytes, type:", blob.type);
    if (!blob.size) return false;

    stopServerAudio();
    SYNTH?.cancel();
    activeAudioUrl = URL.createObjectURL(blob);
    activeAudio = new Audio(activeAudioUrl);
    activeAudio.onplay = () => {
      console.log("[TTS] playing audio");
      useStore.getState().setVoiceProfile({
        name: "Microsoft Ryan Neural",
        lang: "en-GB",
        tier: "cinematic",
      });
      useStore.getState().setOrb("speaking");
      mic.onTtsStart();
    };
    activeAudio.onended = () => {
      console.log("[TTS] audio ended");
      stopServerAudio();
      if (useStore.getState().orbState === "speaking") useStore.getState().setOrb("idle");
      mic.onTtsEnd();
    };
    activeAudio.onerror = (e) => {
      console.error("[TTS] audio play error:", e);
      stopServerAudio();
      if (useStore.getState().orbState === "speaking") useStore.getState().setOrb("idle");
      mic.onTtsEnd();
    };
    await activeAudio.play();
    return true;
  } catch (e) {
    console.error("[TTS] server TTS failed:", e);
    stopServerAudio();
    return false;
  }
}

export function speak(text: string): void {
  if (!useStore.getState().voiceEnabled) {
    console.log("[TTS] voice disabled, skipping");
    return;
  }
  const clean = cleanSpeechText(text);
  if (!clean) return;
  console.log("[TTS] speaking:", clean.slice(0, 80));
  // Hard-stop the streaming queue first so legacy speak() never overlaps
  // an in-progress streamSpeak burst.
  cancelStreamingTts();
  void (async () => {
    if (await speakWithServerTts(clean)) return;
    console.log("[TTS] server TTS failed, trying browser TTS");
    speakWithBrowserTts(clean);
  })();
}

// ── Streaming TTS API ──────────────────────────────────────────────────────
// Called from App.tsx as assistant tokens arrive. Detects newly-completed
// sentences (anything ending in . ! ? or newline) and queues each one
// for synthesis. On `isFinal`, flushes any trailing fragment too.
// Audio segments play strictly in order; later segments wait their turn.
export function streamSpeak(id: string, fullText: string, isFinal: boolean): void {
  if (!useStore.getState().voiceEnabled) {
    console.log("[TTS:stream] voice disabled, skip");
    return;
  }

  // New message → reset queue + state so we don't blend two answers.
  if (id !== streamState.id) {
    console.log("[TTS:stream] NEW message id=%s → cancel previous (was %s)", id, streamState.id);
    cancelStreamingTts();
    streamState.id = id;
    streamState.spokenChars = 0;
  }

  const clean = cleanSpeechText(fullText);
  const unseen = clean.slice(streamState.spokenChars);
  if (!unseen) {
    if (isFinal) maybeMarkStreamDone();
    return;
  }

  // Match runs of text terminated by sentence punctuation. Anything before
  // the last terminator is "complete" and safe to synthesize; the tail
  // (no terminator yet) waits for more tokens.
  const re = /[^.!?\n]+[.!?\n]+/g;
  let m: RegExpExecArray | null;
  let consumed = 0;
  while ((m = re.exec(unseen)) !== null) {
    const seg = m[0].trim();
    if (seg.length >= 3 && /[a-z0-9]/i.test(seg)) {
      console.log("[TTS:stream] SENTENCE detected (%d chars): \"%s\"", seg.length, seg.slice(0, 60));
      void fetchAndEnqueue(seg);
    }
    consumed = m.index + m[0].length;
  }
  streamState.spokenChars += consumed;

  if (isFinal) {
    const tail = clean.slice(streamState.spokenChars).trim();
    if (tail.length >= 2 && /[a-z0-9]/i.test(tail)) {
      console.log("[TTS:stream] FINAL flush tail (%d chars): \"%s\"", tail.length, tail.slice(0, 60));
      void fetchAndEnqueue(tail);
      streamState.spokenChars = clean.length;
    }
    maybeMarkStreamDone();
  }
}

function maybeMarkStreamDone(): void {
  // If everything fetched + played, nothing to do. The audio queue's own
  // playNext() will fire mic.onTtsEnd() and reset orb when it drains.
}

async function fetchAndEnqueue(text: string): Promise<void> {
  const gen = streamGeneration;     // snapshot — detect stale fetches
  pendingFetches++;
  console.log("[TTS:fetch] START gen=%d, pendingFetches=%d, text=\"%s\"", gen, pendingFetches, text.slice(0, 50));
  try {
    const resp = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (gen !== streamGeneration) {
      console.log("[TTS:fetch] STALE (gen %d vs %d) — dropping", gen, streamGeneration);
      return;  // cancel happened while we were fetching
    }
    console.log("[TTS:fetch] response status=%d, gen=%d", resp.status, gen);
    if (!resp.ok) {
      console.warn("[TTS:fetch] server returned %d — dropping", resp.status);
      return;
    }
    const blob = await resp.blob();
    if (gen !== streamGeneration) {
      console.log("[TTS:fetch] STALE after blob — dropping");
      return;
    }
    console.log("[TTS:fetch] blob size=%d", blob.size);
    if (!blob.size) return;
    enqueueAudio(blob, gen);
  } catch (e) {
    console.warn("[TTS] segment fetch failed:", e);
  } finally {
    // Only decrement if this fetch belongs to the current generation.
    // Stale fetches (from a cancelled stream) must not touch the counter.
    if (gen === streamGeneration) {
      pendingFetches--;
      console.log("[TTS:fetch] END pendingFetches=%d", pendingFetches);
    } else {
      console.log("[TTS:fetch] END (stale gen=%d, not decrementing)", gen);
    }
  }
}

function enqueueAudio(blob: Blob, gen: number): void {
  // Final-instant generation check — if a cancel slipped in after the
  // fetch resolved but before this synchronous push, drop the blob.
  if (gen !== streamGeneration) {
    console.log("[TTS:enqueue] STALE (gen %d vs %d) — drop %d bytes", gen, streamGeneration, blob.size);
    return;
  }
  const url = URL.createObjectURL(blob);
  ttsQueue.push({ url });
  console.log("[TTS:enqueue] queued blob %d bytes, queueLen=%d, ttsPlaying=%s", blob.size, ttsQueue.length, ttsPlaying);
  if (!ttsPlaying) playNext();
}

function releaseActive() {
  if (activeUrl) {
    try { URL.revokeObjectURL(activeUrl); } catch { /* noop */ }
    activeUrl = null;
  }
}

function handleClipFinished(_reason: "ended" | "error") {
  // Called when the shared <audio> element finishes (or errors) a clip.
  // Ignore if a cancel bumped the generation while this clip was playing —
  // the queue/state already advanced and a new burst may be running.
  if (activeGeneration !== streamGeneration) {
    console.log("[TTS:play] %s ignored (stale gen %d vs %d)", _reason, activeGeneration, streamGeneration);
    releaseActive();
    return;
  }
  releaseActive();
  ttsPlaying = false;
  playNext();
}

function playNext(): void {
  if (!playerAudio) {
    // No Audio support — nothing to do; drop the queue gracefully.
    ttsQueue.length = 0;
    ttsPlaying = false;
    return;
  }
  // Re-entrancy guard: if a clip is already mid-play in the current
  // generation, do nothing. The clip's "ended" callback will advance.
  if (ttsPlaying && activeGeneration === streamGeneration) {
    return;
  }
  const next = ttsQueue.shift();
  if (!next) {
    ttsPlaying = false;
    releaseActive();
    console.log("[TTS:play] queue empty, pendingFetches=%d", pendingFetches);
    if (pendingFetches <= 0) {
      if (useStore.getState().orbState === "speaking") useStore.getState().setOrb("idle");
      mic.onTtsEnd();
    } else {
      // More clips on the way — wait briefly then re-check, but only if
      // the generation hasn't changed (cancel would have nuked the wait).
      const wakeGen = streamGeneration;
      setTimeout(() => {
        if (wakeGen === streamGeneration && !ttsPlaying) playNext();
      }, 60);
    }
    return;
  }
  // Stop anything still bound to the player (defensive — shouldn't be
  // playing, but src may be set from the previous clip).
  try { playerAudio.pause(); } catch { /* noop */ }
  releaseActive();

  activeUrl = next.url;
  activeGeneration = streamGeneration;
  ttsPlaying = true;
  console.log("[TTS:play] playing clip, remaining=%d, gen=%d", ttsQueue.length, activeGeneration);
  if (useStore.getState().orbState !== "speaking") {
    useStore.getState().setOrb("speaking");
    mic.onTtsStart();
  }
  playerAudio.src = next.url;
  // Re-fire generation check on the play() promise: if a cancel bumped
  // generation between src= and the play resolution, abort.
  const startGen = activeGeneration;
  playerAudio.play().catch((err) => {
    console.warn("[TTS:play] play() rejected:", err);
    if (startGen !== streamGeneration) return;   // cancelled
    handleClipFinished("error");
  });
}

export function cancelStreamingTts(): void {
  // Pause the shared player FIRST — guarantees no two clips ever overlap
  // because the OS only ever plays ONE element at a time.
  if (playerAudio) {
    try {
      playerAudio.pause();
      playerAudio.currentTime = 0;
      // Clear src so the element doesn't hold a reference to a revoked URL.
      playerAudio.removeAttribute("src");
      playerAudio.load();
    } catch { /* noop */ }
  }
  releaseActive();
  // Drop every queued URL.
  for (const c of ttsQueue) {
    try { URL.revokeObjectURL(c.url); } catch { /* noop */ }
  }
  ttsQueue.length = 0;
  ttsPlaying = false;
  // Also kill legacy speak() audio and any browser SpeechSynthesis.
  stopServerAudio();
  try { SYNTH?.cancel(); } catch { /* noop */ }
  // Bump generation so all stale fetches / timeouts / play() promises
  // recognize themselves and bail.
  streamGeneration++;
  activeGeneration = streamGeneration;
  pendingFetches = 0;
  streamState.id = "";
  streamState.spokenChars = 0;
  console.log("[TTS:cancel] reset — generation now %d", streamGeneration);
}

function speakWithBrowserTts(clean: string): void {
  if (!SYNTH) return;
  stopServerAudio();
  SYNTH.cancel();
  const u = new SpeechSynthesisUtterance(clean);
  const v = pickVoice();
  if (v) u.voice = v;
  u.lang = v?.lang || "en-GB";
  u.rate = 0.94;
  u.pitch = 0.82;
  u.volume = 1.0;
  u.onstart = () => {
    useStore.getState().setOrb("speaking");
    mic.onTtsStart();
  };
  u.onend = () => {
    if (useStore.getState().orbState === "speaking") useStore.getState().setOrb("idle");
    mic.onTtsEnd();
  };
  SYNTH.speak(u);
}

export function stopSpeaking() {
  stopServerAudio();
  cancelStreamingTts();
  SYNTH?.cancel();
}

// --- STT (Server-side via MediaRecorder + /api/stt) ---
// Wake-word gated: every utterance is transcribed, but ONLY utterances
// that contain "jarvis" / "hey jarvis" are forwarded to the chat. Other
// speech is discarded silently so the model never reacts to ambient talk.
// Once awake the mic stays "armed" for FOLLOWUP_WINDOW_MS so quick
// follow-ups don't need to repeat the wake word.

// VAD constants. SILENCE_THRESHOLD is the *floor* below which audio counts
// as silence; the actual detection threshold floats up dynamically based on
// a noise baseline learned during the first second of every mic session.
const SILENCE_THRESHOLD   = 0.05;
const SILENCE_TIMEOUT_MS  = 900;       // silence this long = end of utterance
const MIN_RECORDING_MS    = 350;       // ignore clips shorter than this
const MAX_RECORDING_MS    = 8_000;     // force-flush clips longer than this
const BASELINE_WINDOW_MS  = 1_000;     // learn ambient noise level over 1 s
const BASELINE_MULTIPLIER = 1.8;       // require lvl > baseline * mult to count as voice

// ── Speak-time cancel ("mute mic except cancel") ────────────────────────────
// While JARVIS is speaking the mic is muted to normal commands — VAD is paused
// so we never transcribe ambient talk or our own TTS. We keep ONE ear open for
// a stop word: a sustained, clearly-louder-than-ambient voice (echo residue
// won't survive the sustain window) triggers a short "cancel-probe" recording.
// That probe is checked ONLY for "cancel"/"stop" — TTS keeps playing unless a
// stop word is actually heard. Probe audio is NEVER submitted as a chat.
const BARGE_IN_MULTIPLIER = 3.2;       // voice must exceed baseline * this
const BARGE_IN_FLOOR      = 0.12;      // and clear this absolute level
const BARGE_IN_SUSTAIN_MS = 220;       // for this long, continuously
// Stop words that cut TTS when heard during a cancel-probe.
const CANCEL_RE = /\b(?:cancel|nevermind|never\s*mind|shut\s*up|stop(?:\s+(?:talking|speaking))?|be\s+quiet|quiet|enough|hush)\b/i;
const CANCEL_PROBE_MS = 1600;          // how long to listen for the stop word

// Whisper hallucinations to suppress (mirror of server filter).
const HALLUCINATION_RE = /^\s*(?:thanks?[\s,.!?]*(?:for\s+watching|for\s+listening)?[\s,.!?]*(?:everyone|guys|all)?[\s,.!?]*|thank\s+you[\s,.!?]*(?:for\s+watching|for\s+listening|so\s+much)?[\s,.!?]*|(?:please\s+)?(?:like\s*(?:and\s+)?)?subscribe[\s,.!?]*(?:to\s+my\s+channel)?[\s,.!?]*|bye(?:\s*bye)?[\s,.!?]*|goodbye[\s,.!?]*|(?:see|catch)\s+you\s+(?:later|next\s+time)[\s,.!?]*|you[\s,.!?]*|[.!?,…\s♪♫]+)\s*$/i;
// Non-lexical interjections / vocal noise (throat-clears, "oh", "uh", "hmm").
// In the armed follow-up window these would otherwise auto-submit as a chat
// and cancel any in-flight task. Drop them — they carry no command.
const FILLER_RE = /^\s*(?:oh+|uh+|um+|hmm+|hm|ah+|aha|eh+|mm+|er+|huh|ugh|oof|whoa|oops|mhm|uh[\s-]*huh|oh\s+my|yeah|yep|nope|hu)[\s,.!?…]*$/i;
const FOLLOWUP_WAKE_MS  = 10_000;
const FOLLOWUP_REPLY_MS = 20_000;
// VAD often chops one spoken sentence into 2+ STT clips on short pauses.
// Buffer submissions this long and join consecutive clips into ONE chat, so a
// mid-sentence pause doesn't fire twice (the 2nd request cancelling the 1st).
const STT_COALESCE_MS = 800;
const SLEEP_PHRASES = /\b(?:stop listening|go to sleep|jarvis stop|sleep mode|nevermind|never mind|that's all|that is all)\b/i;

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

function detectWake(text: string): boolean {
  if (WAKE_STRICT_RE.test(text) || WAKE_SHAPE_RE.test(text)) return true;
  // Token-level Levenshtein fallback — catches odd Whisper outputs like
  // "Jarves," "Jervis," "Charvis," "Yarvis," etc.
  for (const tok of text.split(/[\s,.\!\?\-:;'"]+/)) {
    if (isJarvisLike(tok)) return true;
  }
  return false;
}

function stripWakeWord(text: string): string {
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

export class JarvisMic {
  private analyser: AnalyserNode | null = null;
  private audioCtx: AudioContext | null = null;
  private rafId: number | null = null;
  private stream: MediaStream | null = null;

  // Recording state
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private isRecording = false;
  private recordingStartTime = 0;
  private silenceStart = 0;
  // Rolling ambient noise floor — learned during the first second of every
  // session so we can distinguish actual speech from constant background
  // hum (fans, A/C, traffic) that would otherwise pin the VAD open forever.
  private baselineLvl = 0;
  private baselineSamples = 0;
  private baselineStartedAt = 0;
  private _wantListening = false;
  private _onTranscript: ((text: string, isFinal: boolean) => void) | null = null;
  private _onWake: ((phrase: string) => void) | null = null;
  private _transcribing = false;
  private _coalesceBuf: string[] = [];
  private _coalesceTimer: ReturnType<typeof setTimeout> | null = null;
  // Wake-word gate
  private _awakeUntil = 0;        // unix ms; while now < this, accept everything
  private _ttsActive = false;     // JARVIS is talking — mic muted except "cancel"
  private _loudRunStart = 0;      // unix ms the current loud-while-speaking run began
  private _recordingIsProbe = false;  // current capture is a cancel-probe (never submit)
  private _probeTimer: ReturnType<typeof setTimeout> | null = null;

  // Called from voice.speak() when TTS begins / ends.
  onTtsStart() {
    this._ttsActive = true;
    this._loudRunStart = 0;
    // Drop any in-flight capture (would otherwise pick up JARVIS itself).
    if (this.isRecording) this._stopRecording();
    if (this._wantListening) {
      useStore.getState().setMicMode("speaking");
      useStore.getState().setMicStatus(
        useStore.getState().bargeIn
          ? "JARVIS speaking · say “cancel” to stop"
          : "JARVIS speaking · mic muted",
      );
    }
  }

  onTtsEnd() {
    this._ttsActive = false;
    this._loudRunStart = 0;
    // Tear down any cancel-probe still in flight; its audio must never submit.
    if (this._probeTimer) { clearTimeout(this._probeTimer); this._probeTimer = null; }
    if (this.isRecording) this._stopRecording();
    // After JARVIS finishes, arm a generous follow-up window so the user
    // can reply naturally — no second wake word needed.
    this._awakeUntil = Date.now() + FOLLOWUP_REPLY_MS;
    if (this._wantListening) {
      useStore.getState().setMicMode("armed");
      useStore.getState().setMicStatus(`armed · ${Math.round(FOLLOWUP_REPLY_MS/1000)}s to reply`);
    }
  }

  // The user spoke up while JARVIS is talking. Start a brief recording that is
  // checked ONLY for a stop word — TTS keeps playing meanwhile. If no stop word
  // is heard the audio is discarded; it is never submitted as a chat.
  private _startCancelProbe() {
    this._loudRunStart = 0;
    if (this.isRecording || this._transcribing) return;
    console.log("[STT] loud voice while speaking — cancel-probe armed");
    this._startRecording();
    this._recordingIsProbe = true;
    if (this._probeTimer) clearTimeout(this._probeTimer);
    this._probeTimer = setTimeout(() => {
      this._probeTimer = null;
      this._stopRecording();
    }, CANCEL_PROBE_MS);
    if (this._wantListening) {
      useStore.getState().setMicStatus("listening for “cancel”…");
    }
  }

  available(): boolean {
    return Boolean(navigator.mediaDevices?.getUserMedia);
  }

  async start(onTranscript: (text: string, isFinal: boolean) => void, onWake?: (phrase: string) => void) {
    if (this._wantListening) return;
    this._wantListening = true;
    this._onTranscript = onTranscript;
    this._onWake = onWake ?? null;
    await this._initAudio();
  }

  stop() {
    this._wantListening = false;
    this._onTranscript = null;
    this._onWake = null;
    this._awakeUntil = 0;
    // Drop any buffered STT clips + cancel a pending coalesce flush so a late
    // submission can't fire after the mic is stopped.
    if (this._coalesceTimer) { clearTimeout(this._coalesceTimer); this._coalesceTimer = null; }
    this._coalesceBuf = [];
    // Tear down a cancel-probe if one is running.
    if (this._probeTimer) { clearTimeout(this._probeTimer); this._probeTimer = null; }
    this._recordingIsProbe = false;
    this._loudRunStart = 0;
    this._stopRecording();
    this._stopAudioMeter();
    useStore.getState().setMicEnabled(false);
    useStore.getState().setMicMode("dormant");
    useStore.getState().setMicStatus("");
    useStore.getState().setOrb("idle");
  }

  private async _initAudio() {
    try {
      // Echo cancellation is what makes barge-in viable: it strips most of
      // JARVIS's own TTS out of the mic signal so we don't transcribe
      // ourselves or false-trigger the interrupt detector.
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (e) {
      console.warn("getUserMedia denied", e);
      useStore.getState().setMicStatus("mic blocked");
      return;
    }

    this.audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
    const src = this.audioCtx.createMediaStreamSource(this.stream);
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 512;
    this.analyser.smoothingTimeConstant = 0.4;  // faster response to level changes
    src.connect(this.analyser);

    useStore.getState().setMicEnabled(true);
    useStore.getState().setOrb("listening");
    useStore.getState().setMicStatus("calibrating mic…");

    // Reset baseline state for this session.
    this.baselineLvl = 0;
    this.baselineSamples = 0;
    this.baselineStartedAt = Date.now();

    const freqData = new Uint8Array(this.analyser.frequencyBinCount);
    const tick = () => {
      if (!this.analyser || !this._wantListening) return;
      this.analyser.getByteFrequencyData(freqData);
      let sum = 0;
      for (let i = 0; i < freqData.length; i++) sum += freqData[i];
      const lvl = sum / freqData.length / 255;
      useStore.getState().setAudioLevel(lvl);

      // ── Baseline learning. Only samples taken before any voice has been
      //    detected count, so we learn the real ambient noise floor.
      const elapsed = Date.now() - this.baselineStartedAt;
      if (elapsed < BASELINE_WINDOW_MS && !this.isRecording) {
        this.baselineSamples++;
        this.baselineLvl =
          (this.baselineLvl * (this.baselineSamples - 1) + lvl) / this.baselineSamples;
        if (elapsed >= BASELINE_WINDOW_MS - 33 && this._wantListening) {
          useStore.getState().setMicStatus(
            `listening · noise floor ${(this.baselineLvl * 100).toFixed(1)}%`,
          );
        }
      }

      // Dynamic threshold: max(floor, baseline * multiplier). If the room
      // is loud, the threshold rises so we still detect speech as the
      // crossing event rather than pinning the VAD open permanently.
      const voiceThr = Math.max(
        SILENCE_THRESHOLD,
        this.baselineLvl * BASELINE_MULTIPLIER,
      );

      // Voice activity detection — paused while JARVIS is speaking so we
      // never transcribe our own TTS output.
      if (!this._ttsActive) {
        this._loudRunStart = 0;
        if (lvl > voiceThr) {
          this.silenceStart = 0;
          if (!this.isRecording && !this._transcribing) {
            this._startRecording();
          }
        } else if (this.isRecording) {
          if (!this.silenceStart) {
            this.silenceStart = Date.now();
          } else if (Date.now() - this.silenceStart > SILENCE_TIMEOUT_MS) {
            this._stopRecording();
          }
        }
        // Hard cap on recording length so very long utterances still flush
        // for transcription even if the user never reaches a silent moment.
        if (
          this.isRecording &&
          Date.now() - this.recordingStartTime > MAX_RECORDING_MS
        ) {
          this._stopRecording();
        }
      } else if (useStore.getState().bargeIn) {
        // JARVIS is speaking; mic is muted to normal commands. Keep one ear
        // open for a stop word: a sustained, clearly-louder-than-ambient voice
        // (transient echo residue won't survive the sustain window) arms a
        // short cancel-probe. TTS keeps playing unless the probe hears "cancel".
        const loudThr = Math.max(BARGE_IN_FLOOR, this.baselineLvl * BARGE_IN_MULTIPLIER);
        if (lvl > loudThr) {
          if (!this._loudRunStart) {
            this._loudRunStart = Date.now();
          } else if (
            Date.now() - this._loudRunStart > BARGE_IN_SUSTAIN_MS &&
            !this.isRecording && !this._transcribing
          ) {
            this._startCancelProbe();
          }
        } else {
          this._loudRunStart = 0;
        }
      }

      this.rafId = requestAnimationFrame(tick);
    };
    tick();
  }

  private _startRecording() {
    if (!this.stream || this.isRecording) return;
    // Default: a normal capture. _startCancelProbe() flips this true after.
    this._recordingIsProbe = false;

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "";

    try {
      this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    } catch (e) {
      console.warn("MediaRecorder init failed:", e);
      return;
    }

    this.chunks = [];
    this.recorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    this.recorder.onstop = () => {
      const duration = Date.now() - this.recordingStartTime;
      // Snapshot probe-ness now — onTtsEnd may clear it before transcription.
      const wasProbe = this._recordingIsProbe;
      this._recordingIsProbe = false;
      if (duration >= MIN_RECORDING_MS && this.chunks.length > 0) {
        const blob = new Blob(this.chunks, { type: this.recorder?.mimeType || "audio/webm" });
        this._transcribe(blob, wasProbe);
      }
      this.chunks = [];
    };

    this.recorder.start(100);
    this.isRecording = true;
    this.recordingStartTime = Date.now();
    this.silenceStart = 0;
    useStore.getState().setMicStatus("recording…");
    console.log("[STT] recording started");
  }

  private _stopRecording() {
    if (!this.isRecording || !this.recorder) return;
    this.isRecording = false;
    try {
      if (this.recorder.state === "recording") {
        this.recorder.stop();
      }
    } catch { /* noop */ }
    this.recorder = null;
  }

  private async _transcribe(blob: Blob, isCancelProbe = false) {
    if (this._transcribing) return;
    this._transcribing = true;
    useStore.getState().setMicStatus(isCancelProbe ? "listening for “cancel”…" : "transcribing…");
    console.log("[STT] sending", blob.size, "bytes for transcription", isCancelProbe ? "(cancel-probe)" : "");

    try {
      const form = new FormData();
      form.append("audio", blob, "speech.webm");

      const resp = await fetch("/api/stt", { method: "POST", body: form });
      const result = await resp.json();

      console.log("[STT] result:", result);

      // Cancel-probe: user spoke up while JARVIS was talking. ONLY a stop word
      // does anything here — this audio is never forwarded to the chat.
      if (isCancelProbe) {
        const probe = (result?.text || "").trim();
        if (probe && CANCEL_RE.test(probe)) {
          console.log("[STT] cancel word while speaking — cutting TTS:", probe);
          cancelStreamingTts();
          this._ttsActive = false;
          this._loudRunStart = 0;
          this._awakeUntil = Date.now() + FOLLOWUP_WAKE_MS;
          useStore.getState().setMicMode("armed");
        } else {
          console.log("[STT] cancel-probe, no stop word — ignoring:", probe || "(empty)");
        }
        return;   // probe audio is never submitted
      }

      if (result.text && this._onTranscript) {
        const text = result.text.trim();
        if (!text) return;
        // Client-side guard against Whisper's YouTube-outro hallucinations.
        // Server already filters them, this catches any that slip through.
        if (HALLUCINATION_RE.test(text)) {
          console.log("[STT] discarded hallucination:", text);
          return;
        }
        // Pure vocal noise (oh / uh / hmm) — never submit. Without this an
        // ambient "oh" in the armed window cancels whatever JARVIS is running.
        if (FILLER_RE.test(text)) {
          console.log("[STT] ignored filler:", text);
          return;
        }

        // Sleep command always wins — drop to dormant immediately.
        if (SLEEP_PHRASES.test(text)) {
          this._awakeUntil = 0;
          useStore.getState().setMicMode("dormant");
          useStore.getState().setMicStatus("dormant — say “Hey JARVIS” to wake");
          return;
        }

        const now = Date.now();
        const hasWake = detectWake(text);
        const inFollowup = now < this._awakeUntil;

        if (!hasWake && !inFollowup) {
          // Ambient speech — drop. Brief visual feedback then back to dormant.
          useStore.getState().setMicMode("dormant");
          useStore.getState().setMicStatus(`(ignored) "${text.slice(0, 40)}"`);
          setTimeout(() => {
            if (this._wantListening && useStore.getState().micMode === "dormant") {
              useStore.getState().setMicStatus("listening · say “Hey JARVIS”");
            }
          }, 1200);
          return;
        }

        // Strip wake word so model sees just the command body.
        const cleaned = stripWakeWord(text);
        if (!cleaned) {
          // Bare wake word — arm short window, no submission.
          this._awakeUntil = now + FOLLOWUP_WAKE_MS;
          useStore.getState().setMicMode("armed");
          useStore.getState().setMicStatus("awake · awaiting command");
          this._onWake?.(text);
          return;
        }

        // Real submission. Extend window so the user can continue
        // refining the request without re-saying the wake word.
        this._awakeUntil = now + FOLLOWUP_WAKE_MS;
        useStore.getState().setMicMode("armed");
        this._onWake?.(text);
        this._queueSubmit(cleaned);
      }
    } catch (e) {
      console.error("[STT] transcription failed:", e);
    } finally {
      this._transcribing = false;
      if (this._wantListening) {
        // If JARVIS is still speaking (probe didn't cancel), restore the
        // speaking status rather than the idle listening prompt.
        if (this._ttsActive) {
          useStore.getState().setMicStatus(
            useStore.getState().bargeIn
              ? "JARVIS speaking · say “cancel” to stop"
              : "JARVIS speaking · mic muted",
          );
        } else {
          useStore.getState().setMicStatus("listening · say “Hey JARVIS”");
        }
      }
    }
  }

  // Buffer a real submission and (re)start the coalesce timer. Consecutive
  // clips within STT_COALESCE_MS join into one chat; armed window stays alive.
  private _queueSubmit(text: string) {
    this._coalesceBuf.push(text);
    if (this._coalesceTimer) clearTimeout(this._coalesceTimer);
    useStore.getState().setMicStatus("…");
    this._coalesceTimer = setTimeout(() => this._flushCoalesce(), STT_COALESCE_MS);
  }

  private _flushCoalesce() {
    if (this._coalesceTimer) { clearTimeout(this._coalesceTimer); this._coalesceTimer = null; }
    const joined = this._coalesceBuf.join(" ").replace(/\s+/g, " ").trim();
    this._coalesceBuf = [];
    if (joined && this._onTranscript) this._onTranscript(joined, true);
  }

  private _stopAudioMeter() {
    if (this.rafId) cancelAnimationFrame(this.rafId);
    this.rafId = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.audioCtx?.close().catch(() => undefined);
    this.audioCtx = null;
    this.analyser = null;
    this.stream = null;
    useStore.getState().setAudioLevel(0);
  }
}

export const mic = new JarvisMic();
