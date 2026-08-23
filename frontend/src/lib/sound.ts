/** 音效播放模块 - 支持 Web Audio 合成音效与外部 MP3 文件 */

export type NotificationType = "completed" | "failed";

/** 音效选择：内置合成音或自定义 MP3 */
export type SoundChoice = "default" | "soft" | "cheerful" | "custom";

/** 获取 AudioContext（懒初始化，兼容浏览器） */
let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (audioCtx) return audioCtx;
  try {
    audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
    return audioCtx;
  } catch {
    console.warn("[sound] Web Audio API 不可用，音效已跳过");
    return null;
  }
}

/** 确保 AudioContext 处于 resumed 状态（需用户交互后调用） */
function ensureResumed(ctx: AudioContext): void {
  if (ctx.state === "suspended") {
    ctx.resume().catch(() => {});
  }
}

// ============ 内置合成音效 ============

/** default 音效：完成任务 - 上升双音 (C5→E5) */
function playCompletedDefault(ctx: AudioContext, gainNode: GainNode): void {
  const now = ctx.currentTime;
  const osc1 = ctx.createOscillator();
  osc1.type = "sine";
  osc1.frequency.setValueAtTime(523, now);
  osc1.connect(gainNode);
  osc1.start(now);
  osc1.stop(now + 0.15);

  const osc2 = ctx.createOscillator();
  osc2.type = "sine";
  osc2.frequency.setValueAtTime(659, now + 0.15);
  osc2.connect(gainNode);
  osc2.start(now + 0.15);
  osc2.stop(now + 0.3);
}

/** default 音效：失败 - 下降双音 (C4→G3) */
function playFailedDefault(ctx: AudioContext, gainNode: GainNode): void {
  const now = ctx.currentTime;
  const osc1 = ctx.createOscillator();
  osc1.type = "triangle";
  osc1.frequency.setValueAtTime(262, now);
  osc1.connect(gainNode);
  osc1.start(now);
  osc1.stop(now + 0.2);

  const osc2 = ctx.createOscillator();
  osc2.type = "triangle";
  osc2.frequency.setValueAtTime(196, now + 0.2);
  osc2.connect(gainNode);
  osc2.start(now + 0.2);
  osc2.stop(now + 0.4);
}

/** soft 音效：完成任务 - 柔和单音上行 (A4→C5)，缓起缓落 */
function playCompletedSoft(ctx: AudioContext, gainNode: GainNode): void {
  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(440, now);
  osc.frequency.linearRampToValueAtTime(523, now + 0.5);
  osc.connect(gainNode);
  osc.start(now);
  osc.stop(now + 0.6);
}

/** soft 音效：失败 - 低缓音 (E3)，轻柔短促 */
function playFailedSoft(ctx: AudioContext, gainNode: GainNode): void {
  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(164, now);
  osc.connect(gainNode);
  osc.start(now);
  osc.stop(now + 0.35);
}

/** cheerful 音效：完成任务 - 欢快上行三音 (C5→E5→G5)，三角波 */
function playCompletedCheerful(ctx: AudioContext, gainNode: GainNode): void {
  const now = ctx.currentTime;
  const notes = [523, 659, 784];
  notes.forEach((freq, i) => {
    const osc = ctx.createOscillator();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(freq, now + i * 0.12);
    osc.connect(gainNode);
    osc.start(now + i * 0.12);
    osc.stop(now + i * 0.12 + 0.18);
  });
}

/** cheerful 音效：失败 - 俏皮下行两音 (E5→C5) */
function playFailedCheerful(ctx: AudioContext, gainNode: GainNode): void {
  const now = ctx.currentTime;
  const notes = [659, 523];
  notes.forEach((freq, i) => {
    const osc = ctx.createOscillator();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(freq, now + i * 0.15);
    osc.connect(gainNode);
    osc.start(now + i * 0.15);
    osc.stop(now + i * 0.15 + 0.18);
  });
}

// ============ MP3 播放支持 ============

/** 缓存已加载的 Audio 对象（按 URL 复用） */
const audioCache = new Map<string, HTMLAudioElement>();

/** 通过 HTMLAudioElement 播放外部 MP3 */
function playMp3(url: string, volume: number): void {
  try {
    let audio = audioCache.get(url);
    if (!audio) {
      audio = new Audio(url);
      audio.preload = "auto";
      audioCache.set(url, audio);
    }
    audio.volume = Math.max(0, Math.min(1, volume));
    audio.currentTime = 0;
    const playPromise = audio.play();
    if (playPromise !== undefined) {
      playPromise.catch((e) => {
        console.warn("[sound] MP3 播放失败:", e);
      });
    }
  } catch (e) {
    console.warn("[sound] MP3 播放异常:", e);
  }
}

// ============ 主入口 ============

export interface SoundOptions {
  /** 音效选择：default / soft / cheerful / custom */
  choice?: SoundChoice;
  /** 音量 0~1 */
  volume?: number;
  /** custom 模式下使用的 MP3 文件路径 */
  customUrl?: string;
}

/**
 * 播放通知提示音
 *
 * @param type - 音效类型："completed" | "failed"
 * @param options - 音效配置（choice / volume / customUrl）
 */
export function playNotificationSound(
  type: NotificationType,
  options: SoundOptions = {},
): void {
  const volume = options.volume ?? 0.5;
  const choice = options.choice ?? "default";

  // 自定义 MP3 模式：直接播放用户选择的文件（若有）
  if (choice === "custom" && options.customUrl) {
    playMp3(options.customUrl, volume);
    return;
  }

  const ctx = getAudioContext();
  if (!ctx) return;
  ensureResumed(ctx);

  const now = ctx.currentTime;
  const gainNode = ctx.createGain();
  const clamped = Math.max(0, Math.min(1, volume));

  // 淡入淡出避免爆音
  gainNode.gain.setValueAtTime(0, now);
  gainNode.gain.linearRampToValueAtTime(clamped, now + 0.01);
  gainNode.gain.setValueAtTime(clamped, now + 0.3);
  gainNode.gain.linearRampToValueAtTime(0, now + 0.45);
  gainNode.connect(ctx.destination);

  // 按选择路由到对应合成音
  const isCompleted = type === "completed";
  switch (choice) {
    case "soft":
      if (isCompleted) playCompletedSoft(ctx, gainNode);
      else playFailedSoft(ctx, gainNode);
      break;
    case "cheerful":
      if (isCompleted) playCompletedCheerful(ctx, gainNode);
      else playFailedCheerful(ctx, gainNode);
      break;
    default:
      if (isCompleted) playCompletedDefault(ctx, gainNode);
      else playFailedDefault(ctx, gainNode);
      break;
  }
}
