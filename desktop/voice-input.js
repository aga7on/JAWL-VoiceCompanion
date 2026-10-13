const DEFAULT_MIC_CONFIG = Object.freeze({
  openRms: 0.02,
  closeRms: 0.012,
  silenceMs: 1200,
  preRollMs: 120,
  minSpeechMs: 60,
  releaseMs: 120,
});

function boundedNumber(value, fallback, min, max) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback;
}

export function normalizeMicConfig(input = {}) {
  const openRms = boundedNumber(input.openRms ?? input.gate_open, DEFAULT_MIC_CONFIG.openRms, 0.001, 0.25);
  const closeRms = boundedNumber(input.closeRms ?? input.gate_close, DEFAULT_MIC_CONFIG.closeRms, 0.0005, openRms * 0.95);
  return Object.freeze({
    openRms,
    closeRms,
    silenceMs: boundedNumber(input.silenceMs ?? input.silence_ms, DEFAULT_MIC_CONFIG.silenceMs, 300, 5000),
    preRollMs: boundedNumber(input.preRollMs ?? input.pre_roll_ms, DEFAULT_MIC_CONFIG.preRollMs, 0, 500),
    minSpeechMs: boundedNumber(input.minSpeechMs, DEFAULT_MIC_CONFIG.minSpeechMs, 20, 240),
    releaseMs: boundedNumber(input.releaseMs, DEFAULT_MIC_CONFIG.releaseMs, 40, 400),
  });
}

export function uploadUtteranceFor(mic) {
  return mic.flushDestination || mic.utterance;
}

export function completeMicFlushBoundary(mic, lastVoiceAt, nextUtterance) {
  mic.flushDestination = null;
  if (mic.inputGate.lastVoiceAt > lastVoiceAt) return {resumed: true, utterance: null};
  const utterance = mic.utterance;
  mic.utterance = nextUtterance;
  mic.heard = false;
  return {resumed: false, utterance};
}

export function detachMicState(state, mic) {
  if (state.mic !== mic) return false;
  if (mic) mic.active = false;
  state.mic = null;
  state.micActive = false;
  return true;
}

export function invalidatePendingCapture({lease, pendingLease, captureGeneration, currentGeneration, invalidate}) {
  if (lease !== pendingLease || captureGeneration !== currentGeneration) return false;
  invalidate();
  return true;
}

export function requireVoiceResponseOk(response, operation) {
  if (response.ok) return response;
  const error = new Error(`${operation} failed (HTTP ${response.status})`);
  error.code = 'VOICE_CAPTURE_HTTP_ERROR';
  error.status = response.status;
  throw error;
}

function frameRms(samples) {
  let energy = 0;
  for (let i = 0; i < samples.length; i += 1) energy += samples[i] * samples[i];
  return samples.length ? Math.sqrt(energy / samples.length) : 0;
}

// Bounded gate for one live microphone stream. Closed-gate audio is kept only
// in a short rolling pre-roll and is returned only after qualified speech.
export class MicInputGate {
  constructor(config = {}) {
    this.config = normalizeMicConfig(config);
    this.preRoll = [];
    this.preRollDurationMs = 0;
    this.onsetDurationMs = 0;
    this.releaseDurationMs = 0;
    this.open = false;
    this.lastVoiceAt = 0;
    this.lastRms = 0;
    this.peakRms = 0;
  }

  push(samples, sampleRate, nowMs = performance.now()) {
    const frame = samples instanceof Float32Array ? samples.slice() : new Float32Array(samples);
    const durationMs = sampleRate > 0 ? frame.length * 1000 / sampleRate : 0;
    const rms = frameRms(frame);
    this.lastRms = rms;
    this.peakRms = Math.max(this.peakRms, rms);

    if (!this.open) {
      this.preRoll.push({frame, durationMs});
      this.preRollDurationMs += durationMs;
      const onsetHistoryMs = this.config.preRollMs + this.config.minSpeechMs;
      while (this.preRoll.length > 1 && this.preRollDurationMs - this.preRoll[0].durationMs >= onsetHistoryMs) {
        this.preRollDurationMs -= this.preRoll.shift().durationMs;
      }
      if (rms >= this.config.openRms) this.onsetDurationMs += durationMs;
      else this.onsetDurationMs = 0;
      if (this.onsetDurationMs < this.config.minSpeechMs) {
        return {opened: false, closed: false, frames: [], rms, voiceActive: false};
      }
      this.open = true;
      this.lastVoiceAt = nowMs;
      this.releaseDurationMs = 0;
      const frames = this.preRoll.map(item => item.frame);
      this.preRoll = [];
      this.preRollDurationMs = 0;
      return {opened: true, closed: false, frames, rms, voiceActive: true};
    }

    if (rms >= this.config.closeRms) {
      this.lastVoiceAt = nowMs;
      this.releaseDurationMs = 0;
    } else {
      this.releaseDurationMs += durationMs;
    }
    if (this.releaseDurationMs >= this.config.releaseMs) {
      this.open = false;
      this.onsetDurationMs = 0;
      this.releaseDurationMs = 0;
      this.preRoll = [];
      this.preRollDurationMs = 0;
      return {opened: false, closed: true, frames: [frame], rms, voiceActive: false};
    }
    return {opened: false, closed: false, frames: [frame], rms, voiceActive: true};
  }

  reset() {
    this.preRoll = [];
    this.preRollDurationMs = 0;
    this.onsetDurationMs = 0;
    this.releaseDurationMs = 0;
    this.open = false;
    this.lastVoiceAt = 0;
    this.lastRms = 0;
    this.peakRms = 0;
  }
}

export class CaptureLease {
  constructor({captureId, fetchImpl = fetch, headers = () => ({'Content-Type': 'application/json'}), onLost = () => {}}) {
    this.captureId = captureId;
    this.fetchImpl = fetchImpl;
    this.headers = headers;
    this.onLost = onLost;
    this.leaseId = null;
    this.config = normalizeMicConfig();
    this.renewTimer = null;
    this.renewing = false;
    this.released = false;
    this.acquirePromise = null;
    this.releasePromise = null;
  }

  async request(action) {
    const response = await this.fetchImpl('/api/voice/capture', {
      method: 'POST',
      credentials: 'include',
      headers: this.headers(),
      signal: AbortSignal.timeout(5000),
      body: JSON.stringify({
        action,
        owner: 'desktop',
        capture_id: this.captureId,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data?.ok === false) {
      throw new Error(data?.error || `voice capture ${action} failed (HTTP ${response.status})`);
    }
    return data;
  }

  async acquire() {
    // The caller already chose this unique capture_id, so even a lost HTTP
    // response can be followed by a safe best-effort release.
    this.leaseId = this.captureId;
    const acquirePromise = this.request('acquire');
    this.acquirePromise = acquirePromise;
    let data;
    try {
      data = await acquirePromise;
    } finally {
      if (this.acquirePromise === acquirePromise) this.acquirePromise = null;
    }
    if (data.owner !== 'desktop' || data.capture_id !== this.captureId) {
      throw new Error('voice capture lease response does not match this desktop client');
    }
    // Capture settings are a per-start snapshot. Renewal extends ownership
    // only; changes become effective on the next acquire.
    this.config = normalizeMicConfig(data);
    const ttl = boundedNumber(data.lease_ttl_ms, 15000, 3000, 120000);
    const interval = Math.min(60000, Math.max(1000, Math.floor(ttl / 3)));
    return {config: this.config, renewAfterMs: interval};
  }

  startRenewal(intervalMs) {
    this.stopRenewal();
    this.released = false;
    const interval = boundedNumber(intervalMs, 15000, 1000, 60000);
    this.renewTimer = setInterval(() => { void this.renew(); }, interval);
  }

  async renew() {
    if (this.renewing || this.released || !this.leaseId) return;
    this.renewing = true;
    try {
      const data = await this.request('renew');
      if (data.owner !== 'desktop' || data.capture_id !== this.captureId) {
        throw new Error('voice capture renewal response does not match this desktop client');
      }
    } catch (error) {
      this.stopRenewal();
      if (!this.released) this.onLost(error);
    } finally {
      this.renewing = false;
    }
  }

  stopRenewal() {
    if (this.renewTimer !== null) clearInterval(this.renewTimer);
    this.renewTimer = null;
  }

  async release() {
    this.stopRenewal();
    if (this.releasePromise) return this.releasePromise;
    if (this.released && !this.acquirePromise) return;
    this.released = true;
    this.releasePromise = (async () => {
      const acquirePromise = this.acquirePromise;
      if (acquirePromise) await acquirePromise.catch(() => {});
      if (!this.leaseId) return;
      try { await this.request('release'); } catch { /* server expiry remains bounded */ }
      this.leaseId = null;
    })();
    try { await this.releasePromise; }
    finally { this.releasePromise = null; }
  }
}

export {DEFAULT_MIC_CONFIG};
