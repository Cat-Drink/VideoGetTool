/** 音效播放模块 - 使用 Web Audio API 生成提示音（无需外部音效文件） */

export type NotificationType = "completed" | "failed";

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

/**
 * 播放任务完成提示音（上升双音）
 * 音高：C5(523Hz) → E5(659Hz)，各持续 150ms
 */
function playCompletedSound(ctx: AudioContext, gainNode: GainNode): void {
  const now = ctx.currentTime;

  // 第一音：C5 (523Hz)
  const osc1 = ctx.createOscillator();
  osc1.type = "sine";
  osc1.frequency.setValueAtTime(523, now);
  osc1.connect(gainNode);
  osc1.start(now);
  osc1.stop(now + 0.15);

  // 第二音：E5 (659Hz)
  const osc2 = ctx.createOscillator();
  osc2.type = "sine";
  osc2.frequency.setValueAtTime(659, now + 0.15);
  osc2.connect(gainNode);
  osc2.start(now + 0.15);
  osc2.stop(now + 0.3);
}

/**
 * 播放任务失败提示音（下降双音 + 颤音）
 * 音高：C4(262Hz) → G3(196Hz)，各持续 200ms
 */
function playFailedSound(ctx: AudioContext, gainNode: GainNode): void {
  const now = ctx.currentTime;

  // 第一音：C4 (262Hz) 使用三角波，略带粗糙感
  const osc1 = ctx.createOscillator();
  osc1.type = "triangle";
  osc1.frequency.setValueAtTime(262, now);
  osc1.connect(gainNode);
  osc1.start(now);
  osc1.stop(now + 0.2);

  // 第二音：G3 (196Hz)
  const osc2 = ctx.createOscillator();
  osc2.type = "triangle";
  osc2.frequency.setValueAtTime(196, now + 0.2);
  osc2.connect(gainNode);
  osc2.start(now + 0.2);
  osc2.stop(now + 0.4);
}

/**
 * 播放通知提示音
 *
 * @param type - 音效类型："completed" | "failed"
 * @param volume - 音量 0~1，默认 0.5
 */
export function playNotificationSound(type: NotificationType, volume: number = 0.5): void {
  const ctx = getAudioContext();
  if (!ctx) return;

  ensureResumed(ctx);

  const now = ctx.currentTime;

  // 主音量控制
  const gainNode = ctx.createGain();
  gainNode.gain.setValueAtTime(Math.max(0, Math.min(1, volume)), now);

  // 淡入淡出避免爆音
  gainNode.gain.setValueAtTime(0, now);
  gainNode.gain.linearRampToValueAtTime(Math.max(0, Math.min(1, volume)), now + 0.01);
  gainNode.gain.setValueAtTime(Math.max(0, Math.min(1, volume)), now + 0.3);
  gainNode.gain.linearRampToValueAtTime(0, now + 0.45);

  gainNode.connect(ctx.destination);

  if (type === "completed") {
    playCompletedSound(ctx, gainNode);
  } else {
    playFailedSound(ctx, gainNode);
  }
}
