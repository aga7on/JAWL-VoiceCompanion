// JAWL Companion app — single compact window (ADR-046).
// The 3D character lives in the left stage (app-scene.js, same origin: no
// BroadcastChannel/IPC bridge needed), all functions in the side rail.
// Talks to the companion server directly; no browser tabs, no ports in UI.

const API = {
  csrf: null,
  headers() {
    const h = {'Content-Type': 'application/json'};
    if (this.csrf) h['X-Companion-CSRF'] = this.csrf;
    return h;
  },
};

const state = {
  session: null,
  thinking: false,
  mic: null,
  micActive: false,
  voiceSessionId: null,
  voiceCorrelationId: null,
  voiceSequence: 0,
  speechGeneration: 0,
  speechPlayback: null,
};
let micStartGeneration = 0;
let micStarting = false;
let pendingCaptureLease = null;

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------

async function boot() {
  try {
    const r = await fetch('/api/session', {credentials: 'include', cache: 'no-store'});
    const s = await r.json();
    API.csrf = s.csrf_token || null;
    window.__jcsrf = API.csrf;
    setConn('ok', 'в контуре');
    refreshAll();
  } catch {
    setConn('err', 'компаньон не отвечает');
  }
}

function setConn(kind, text) {
  const dot = document.querySelector('#conn-dot');
  const label = document.querySelector('#conn-status');
  dot.className = 'dot ' + (kind === 'ok' ? 'ok' : kind === 'err' ? 'err' : '');
  label.textContent = text;
}

function setVal(id, text) {
  const el = document.querySelector('#' + id);
  if (el) el.textContent = String(text);
}

// ---------------------------------------------------------------------------
// periodic refresh
// ---------------------------------------------------------------------------

let refreshTimer = null;
function startRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshAll, 10000);
}
async function refreshAll() {
  refreshStatuses();
  refreshJournal();
  refreshMemory();
}

async function refreshMemory() {
  const el = document.querySelector('#memory-log');
  if (!el) return;
  try {
    const r = await fetch('/api/jawl/memory', {credentials: 'include', headers: API.headers()});
    if (!r.ok) { el.textContent = 'память JAWL недоступна (агент не поднят?)'; return; }
    const d = await r.json();
    if (d.status === 'unavailable' || d.configured === false) {
      el.textContent = 'память JAWL не сконфигурирована в этом контуре';
      return;
    }
    const lines = [];
    const facts = d.facts || d.memories || d.items || [];
    if (Array.isArray(facts)) {
      for (const fact of facts.slice(0, 14)) {
        const text = typeof fact === 'string' ? fact : (fact.content || fact.text || fact.summary || JSON.stringify(fact));
        const when = fact.updated_at || fact.timestamp || '';
        lines.push(`${when ? String(when).slice(0, 16) + ' ' : ''}${String(text).slice(0, 100)}`);
      }
    }
    el.textContent = lines.length ? lines.join('\n')
      : 'записей пока нет — JAWL пополняет память из разговоров и heartbeat';
  } catch { el.textContent = 'память JAWL недоступна'; }
}

async function refreshStatuses() {
  try {
    const d = await (await fetch('/api/doctor', {credentials: 'include'})).json();
    const checks = {};
    (d.checks || []).forEach(c => { checks[c.id] = c; });
    setVal('svc-brain', checks.jawl ? checks.jawl.status : '—');
    setVal('svc-jawl', checks.jawl?.ready ? 'готов' : (checks.jawl?.status || '—'));
    setVal('svc-panel', 'в контуре');
    const ts = await (await fetch('/api/tts/status', {credentials: 'include'})).json();
    setVal('tts-provider', ts.model || ts.provider || '—');
    setVal('tts-status', ts.status || '—');
    setVal('svc-tts', ts.status || '—');
    const doctorLog = document.querySelector('#doctor-log');
    if (doctorLog) {
      doctorLog.textContent = (d.checks || []).map(c =>
        `${c.id}: ${c.status}${c.ready === false ? ' ✗' : ' ✓'}`).join('\n') || '—';
    }
    // ASR status: is the voice lane armed?
    const vs = await (await fetch('/api/voice/status', {credentials: 'include'})).json().catch(() => ({}));
    setVal('asr-status', vs.asr || vs.streaming_asr || (vs.configured ? 'настроен' : 'выключен'));
  } catch {
    setConn('err', 'компаньон не отвечает');
  }
}

async function refreshJournal() {
  const el = document.querySelector('#journal-log');
  if (!el) return;
  try {
    const r = await fetch('/api/jawl/journal?limit=12', {credentials: 'include', headers: API.headers()});
    if (!r.ok) { el.textContent = 'журнал недоступен'; return; }
    const d = await r.json();
    const items = d.events || d.journal || d.items || [];
    el.textContent = items.map(e => {
      const ts = e.timestamp || e.time || '';
      const kind = e.type || e.kind || e.event || '';
      const note = e.reason || e.text || e.summary || e.message || '';
      return `${String(ts).slice(11, 19)} ${kind} ${String(note).slice(0, 80)}`;
    }).reverse().join('\n') || '—';
  } catch { el.textContent = '—'; }
}

// ---------------------------------------------------------------------------
// rail navigation
// ---------------------------------------------------------------------------

document.querySelectorAll('nav.rail button[data-tab]').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('nav.rail button').forEach(b => b.classList.remove('active'));
    button.classList.add('active');
    const tab = button.dataset.tab;
    document.querySelectorAll('.side .section').forEach(s =>
      s.classList.toggle('active', s.dataset.section === tab));
    if (tab === 'settings' && typeof loadSettings === 'function') loadSettings();
    if (tab === 'avatar') loadWardrobe();
  });
});

// ---------------------------------------------------------------------------
// chat
// ---------------------------------------------------------------------------

const chatLog = document.querySelector('#chat-log');
const chatInput = document.querySelector('#chat-input');
const chatSend = document.querySelector('#chat-send');
const chatMic = document.querySelector('#chat-mic');
const micState = document.querySelector('#mic-state');
const thinkingEl = document.querySelector('#thinking');
const captionEl = document.querySelector('#avatar-caption');

function addMessage(kind, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + kind;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function setThinking(on) {
  state.thinking = on;
  thinkingEl.classList.toggle('on', on);
  chatSend.disabled = on;
  window.__jawlScene?.setMotionState?.(on ? 'listening' : 'idle');
}

function showCaption(text) {
  captionEl.textContent = text;
  captionEl.classList.remove('dim');
  clearTimeout(showCaption._t);
  showCaption._t = setTimeout(() => captionEl.classList.add('dim'), 9000);
}

// one place for a finished turn: text + face + voice
function handleEnvelope(envelope, {speak = true} = {}) {
  if (!envelope) return;
  if (envelope.text) {
    addMessage('assistant', envelope.text);
    showCaption(envelope.text);
  }
  if (!window.__jawlScene?.applyAvatarEnvelope?.(envelope)) {
    window.__jawlScene?.setEmotion?.(envelope.emotion?.id || 'neutral');
  }
  setVal('avatar-current', envelope.emotion?.id || 'neutral');
  if (speak && envelope.speak !== false && envelope.text) speakFinal(envelope);
}

async function sendChat() {
  const text = chatInput.value.trim();
  if (!text || state.thinking) return;
  cancelSpeechPlayback();
  chatInput.value = '';
  addMessage('user', text);
  setThinking(true);
  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({text}),
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let final = null;
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      let nl;
      while ((nl = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        try {
          const event = JSON.parse(line);
          if (event.type === 'final') final = event.response;
        } catch { /* partial line */ }
      }
    }
    if (final) handleEnvelope(final);
    else addMessage('system', 'Ход завершился без ответа.');
  } catch (error) {
    addMessage('system', 'Ошибка связи: ' + error.message);
  } finally {
    setThinking(false);
  }
}

chatSend.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

// ---------------------------------------------------------------------------
// speech: /api/tts/stream + lip sync from the played audio
// ---------------------------------------------------------------------------

let lipContext = null;
function publishSpeechState(playback, eventState) {
  const now = performance.now();
  window.dispatchEvent(new CustomEvent('jawl-speech-state', {detail: {
    state: eventState,
    generation: playback.generation,
    activeSources: playback.sources?.size || 0,
    sourcePeak: playback.sourcePeak || 0,
    elapsedMs: Math.max(0, Math.round(now - playback.startedAt)),
  }}));
}

function releaseSpeechPlayback(playback, eventState = null) {
  if (!playback || state.speechPlayback !== playback) return;
  state.speechPlayback = null;
  setSpeechStopEnabled(false);
  if (eventState === 'cancel' || eventState === 'error') cancelRemoteSpeech(playback);
  playback.abortController.abort();
  for (const source of playback.sources) {
    source.onended = null;
    try { source.stop(); } catch {}
    try { source.disconnect(); } catch {}
  }
  playback.sources.clear();
  if (playback.frameId !== null) cancelAnimationFrame(playback.frameId);
  playback.frameId = null;
  playback.analyser?.disconnect();
  window.__jawlScene?.setLipLevel(0);
  window.__jawlScene?.setMotionState?.(state.mic?.heard ? 'listening' : 'idle');
  if (eventState) publishSpeechState(playback, eventState);
}

function cancelRemoteSpeech(playback) {
  if (!playback?.requestDispatched || playback.remoteCancelSent) return;
  playback.remoteCancelSent = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1500);
  try {
    void fetch('/api/tts/cancel', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({request_id: playback.requestId}),
      keepalive: true,
      signal: controller.signal,
    }).catch(() => {}).finally(() => clearTimeout(timeout));
  } catch {
    clearTimeout(timeout);
  }
}

function cancelSpeechPlayback() {
  state.speechGeneration += 1;
  releaseSpeechPlayback(state.speechPlayback, 'cancel');
}

function setSpeechStopEnabled(enabled) {
  const button = document.querySelector('#speech-stop');
  if (button) button.disabled = !enabled;
}

document.querySelector('#speech-stop')?.addEventListener('click', cancelSpeechPlayback);
setSpeechStopEnabled(false);

async function speakFinal(envelope) {
  cancelSpeechPlayback();
  const generation = state.speechGeneration;
  const playback = {
    generation,
    requestId: crypto.randomUUID(),
    requestDispatched: false,
    remoteCancelSent: false,
    abortController: new AbortController(),
    sources: new Set(),
    sourcePeak: 0,
    analyser: null,
    frameId: null,
    startedAt: performance.now(),
  };
  state.speechPlayback = playback;
  setSpeechStopEnabled(true);
  try {
    const {consumeSpeechStream} = await import('./speech-stream.js');
    if (state.speechPlayback !== playback || generation !== state.speechGeneration) return;
    playback.requestDispatched = true;
    const response = await fetch('/api/tts/stream', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({text: envelope.text, request_id: playback.requestId}),
      signal: playback.abortController.signal,
    });
    if (state.speechPlayback !== playback || generation !== state.speechGeneration) return;
    if (!response.ok || !response.body) {
      const error = new Error('TTS_STREAM_UNAVAILABLE');
      error.code = 'TTS_STREAM_UNAVAILABLE';
      error.status = response.status;
      throw error;
    }
    if (!response.headers?.get?.('content-type')?.toLowerCase().includes('application/x-ndjson')) {
      const error = new Error('TTS_INVALID_CONTENT_TYPE');
      error.code = 'TTS_INVALID_CONTENT_TYPE';
      throw error;
    }
    if (!lipContext) lipContext = new AudioContext();
    if (lipContext.state === 'suspended') await lipContext.resume();
    if (state.speechPlayback !== playback || generation !== state.speechGeneration) return;
    const analyser = playback.analyser = lipContext.createAnalyser();
    analyser.fftSize = 256;
    analyser.connect(lipContext.destination);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const pump = () => {
      if (state.speechPlayback !== playback || generation !== state.speechGeneration) return;
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
      window.__jawlScene?.setLipLevel(Math.sqrt(sum / data.length) * 2.2);
      if (playback.sources.size) playback.frameId = requestAnimationFrame(pump);
      else window.__jawlScene?.setLipLevel(0);
    };
    const isCurrent = () => state.speechPlayback === playback && generation === state.speechGeneration;
    const promise = consumeSpeechStream(response, {
      audioContext: lipContext,
      signal: playback.abortController.signal,
      isCurrent,
      connectSource: source => source.connect(analyser),
      onSourceStart: source => {
        if (!isCurrent()) return;
        playback.sources.add(source);
        playback.sourcePeak = Math.max(playback.sourcePeak, playback.sources.size);
        if (playback.sources.size === 1) {
          window.__jawlScene?.setMotionState?.('speaking');
          pump();
          publishSpeechState(playback, 'firstscheduled');
        } else if (playback.sources.size > (playback.reportedSourcePeak || 1)) {
          playback.reportedSourcePeak = playback.sources.size;
          publishSpeechState(playback, 'sourcespeak');
        }
      },
      onSourceEnd: source => playback.sources.delete(source),
      onStreamDone: () => { playback.streamDone = true; },
    });
    await promise;
    if (isCurrent()) releaseSpeechPlayback(playback, 'done');
  } catch (error) {
    if (state.speechPlayback === playback && generation === state.speechGeneration) {
      const cancelled = playback.abortController.signal.aborted || error?.code === 'TTS_CANCELLED';
      if (!cancelled) {
        const status = Number.isInteger(error?.status) ? ` (HTTP ${error.status})` : '';
        addMessage('system', `Голосовой ответ не удалось воспроизвести${status}.`);
      }
      releaseSpeechPlayback(playback, cancelled ? 'cancel' : 'error');
    }
  }
  finally {
    if (state.speechPlayback === playback && generation === state.speechGeneration && playback.abortController.signal.aborted) releaseSpeechPlayback(playback, 'cancel');
  }
}

// ---------------------------------------------------------------------------
// microphone: the panel's proven lane (ADR-044/045)
//   worklet PCM -> downsample 16 kHz -> PCM16 base64 -> POST /api/voice/audio
//   silence (2 s) -> POST /api/voice/end  -> responses envelope
// ---------------------------------------------------------------------------

function downsample(samples, fromRate, toRate) {
  if (fromRate === toRate) return samples;
  const ratio = fromRate / toRate;
  const length = Math.floor(samples.length / ratio);
  const result = new Float32Array(length);
  let offset = 0;
  for (let i = 0; i < length; i++) {
    const next = Math.floor((i + 1) * ratio);
    let sum = 0, count = 0;
    for (let j = offset; j < next && j < samples.length; j++) { sum += samples[j]; count++; }
    result[i] = count ? sum / count : 0;
    offset = next;
  }
  return result;
}

function pcm16Base64(samples) {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  const bytes = new Uint8Array(pcm.buffer);
  let binary = '';
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
  }
  return btoa(binary);
}

chatMic.addEventListener('click', () => {
  if (micStarting || state.micActive) void stopMic();
  else void startMic();
});

// ---------------------------------------------------------------------------
// microphone device selection: enumerated labels need one permission grant,
// so we enumerate on first mic use and also on boot when already granted.
// ---------------------------------------------------------------------------

const micSelect = document.querySelector('#mic-select');

function preferredMicId() {
  return localStorage.getItem('jawl.app.micDeviceId') || '';
}
function setPreferredMicId(id) {
  localStorage.setItem('jawl.app.micDeviceId', id || '');
}

async function refreshMicDevices() {
  if (!micSelect || !navigator.mediaDevices?.enumerateDevices) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter(d => d.kind === 'audioinput');
    // labels are empty until permission is granted at least once
    micSelect.replaceChildren();
    const def = document.createElement('option');
    def.value = '';
    def.textContent = inputs.some(d => d.label) ? 'по умолчанию' : 'по умолчанию (метки появятся после первого включения)';
    micSelect.appendChild(def);
    for (const device of inputs) {
      const option = document.createElement('option');
      option.value = device.deviceId;
      option.textContent = device.label || `устройство ${device.deviceId.slice(0, 6)}`;
      micSelect.appendChild(option);
    }
    const wanted = preferredMicId();
    if (wanted && inputs.some(d => d.deviceId === wanted)) micSelect.value = wanted;
  } catch { /* enumeration optional */ }
}

micSelect?.addEventListener('change', () => setPreferredMicId(micSelect.value));
navigator.mediaDevices?.addEventListener?.('devicechange', refreshMicDevices);

async function startMic() {
  if (micStarting || state.micActive) return;
  micStarting = true;
  const startGeneration = ++micStartGeneration;
  let captureLease = null;
  let stream = null;
  let context = null;
  try {
    const micHelpers = await import('./voice-input.js');
    const {createVoiceDraftController} = await import('./voice-draft.js');
    const {CaptureLease, MicInputGate} = micHelpers;
    const captureId = getCaptureClientId();
    captureLease = new CaptureLease({
      captureId,
      headers: () => API.headers(),
      onLost: (error) => {
        if (state.mic?.lease === captureLease ||
            (pendingCaptureLease === captureLease && startGeneration === micStartGeneration)) {
          const mic = state.mic?.lease === captureLease ? state.mic : null;
          if (!mic || !mic.leaseLost) {
            if (mic) mic.leaseLost = true;
            addMessage('system', 'Захват остановлен: ' + error.message);
          }
          void stopMic();
        }
      },
    });
    pendingCaptureLease = captureLease;
    const lease = await captureLease.acquire();
    if (startGeneration !== micStartGeneration) { await captureLease.release(); return; }
    captureLease.startRenewal(lease.renewAfterMs);

    const wanted = preferredMicId();
    const constraints = {
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        ...(wanted ? {deviceId: {exact: wanted}} : {}),
      },
    };
    stream = await navigator.mediaDevices.getUserMedia(constraints);
    if (startGeneration !== micStartGeneration) {
      stream.getTracks().forEach(t => t.stop());
      await captureLease.release();
      return;
    }
    context = new AudioContext();
    await context.audioWorklet.addModule('/mic-processor.js');
    if (startGeneration !== micStartGeneration) {
      stream.getTracks().forEach(t => t.stop());
      await context.close().catch(() => {});
      await captureLease.release();
      return;
    }
    const source = context.createMediaStreamSource(stream);
    const gate = new AudioWorkletNode(context, 'jawl-mic-processor');
    const inputGate = new MicInputGate(captureLease.config);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(gate);
    source.connect(analyser);

    const track = stream.getAudioTracks()[0];
    setVal('mic-device', track?.label || '—');
    // labels are visible now: refresh the picker with real names
    refreshMicDevices();

    const firstUtterance = newVoiceUtterance();
    state.voiceSessionId = firstUtterance.sessionId;
    state.voiceCorrelationId = firstUtterance.correlationId;
    state.mic = {
      stream, context, gate, analyser, inputGate, helpers: micHelpers, lease: captureLease, utterance: firstUtterance,
      uploadQueue: {tail: Promise.resolve(), pending: 0}, finalizing: false, heard: false,
      turnGeneration: 0, active: true, abortController: new AbortController(), flushWaiters: [],
    };
    pendingCaptureLease = null;

    const micCapture = state.mic;
    micCapture.draftText = '';
    micCapture.drafts = createVoiceDraftController({
      getCurrent: () => state.mic === micCapture && micCapture.active &&
        micCapture.heard && !micCapture.finalizing ? {
          session_id: micCapture.utterance.sessionId,
          correlation_id: micCapture.utterance.correlationId,
          capture_id: micCapture.lease.leaseId,
          generation: micCapture.turnGeneration,
        } : null,
      request: async (payload, signal) => {
        const response = await fetch('/api/voice/draft', {
          method: 'POST', credentials: 'include', headers: API.headers(),
          body: JSON.stringify(payload), signal,
        });
        micHelpers.requireVoiceResponseOk(response, 'voice/draft');
        return response.json();
      },
      onDraft: (text) => {
        micCapture.draftText = text;
        if (state.mic === micCapture && micCapture.active && micCapture.heard && !micCapture.finalizing) {
          micState.textContent = text ? 'Слышу (предварительно): ' + text.slice(0, 160) : 'Слушаю…';
        }
      },
    });
    micCapture.draftPoll = setInterval(() => { void micCapture.drafts.tick(); }, 350);
    gate.port.onmessage = (event) => {
      const mic = micCapture;
      if (state.mic !== mic || !mic.active) return;
      if (event.data?.type === 'flushed') {
        mic.flushWaiters.shift()?.();
        return;
      }
      if (!(event.data instanceof ArrayBuffer)) return;
      mic.workletChunks = Math.min(1000000, (mic.workletChunks || 0) + 1);
      mic.lastFrameAt = performance.now();
      const result = mic.inputGate.push(new Float32Array(event.data), context.sampleRate);
      if (result.opened) {
        if (!mic.heard) {
          cancelSpeechPlayback();
          mic.turnGeneration += 1;
          mic.drafts.reset();
          mic.drafts.resume();
        }
        mic.heard = true;
        window.__jawlScene?.setMotionState?.('listening');
        micState.textContent = mic.draftText ? 'Слышу (предварительно): ' + mic.draftText.slice(0, 160) : 'Слушаю…';
      }
      for (const frame of result.frames) uploadChunk(frame, context.sampleRate);
    };

    state.mic.poll = setInterval(() => {
      const mic = state.mic;
      if (mic && mic.active && mic.heard && !mic.finalizing &&
          performance.now() - mic.inputGate.lastVoiceAt >= mic.inputGate.config.silenceMs) {
        void finishUtterance();
      }
    }, 100);

    state.micActive = true;
    chatMic.style.background = 'var(--accent)';
    micState.textContent = 'Микрофон включён — говорите.';
    setVal('mic-state', 'Микрофон включён.');
  } catch (error) {
    stream?.getTracks().forEach(t => t.stop());
    if (context && context.state !== 'closed') await context.close().catch(() => {});
    await captureLease?.release();
    if (pendingCaptureLease === captureLease) pendingCaptureLease = null;
    if (startGeneration === micStartGeneration) micState.textContent = 'Микрофон недоступен: ' + error.message;
  } finally {
    if (startGeneration === micStartGeneration) micStarting = false;
  }
}

function getCaptureClientId() {
  return globalThis.crypto?.randomUUID?.() || `desktop-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function uploadChunk(samples, sampleRate) {
  const mic = state.mic;
  if (!mic) return;
  const utterance = mic.helpers.uploadUtteranceFor(mic);
  const payload = {
    session_id: utterance.sessionId,
    correlation_id: utterance.correlationId,
    owner: 'desktop',
    capture_id: mic.lease.leaseId,
    sample_rate: 16000,
    channels: 1,
    pcm16_base64: pcm16Base64(downsample(samples, sampleRate, 16000)),
  };
  const task = enqueueMicOperation(mic, async () => {
    const response = await fetch('/api/voice/audio', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify(payload),
      signal: mic.abortController.signal,
    });
    return mic.helpers.requireVoiceResponseOk(response, 'voice/audio');
  }, true);
  const fail = (error, reason = error?.code === 'VOICE_CAPTURE_HTTP_ERROR' ? 'http_failure'
    : error?.name === 'TypeError' ? 'transport_failure' : 'upload_failure') => {
    if (state.mic !== mic || !mic.active || mic.uploadFailed) return;
    mic.uploadFailed = true;
    try { voiceCaptureDiagnostic(mic, reason, error); }
    catch { /* optional diagnostics must never prevent capture teardown */ }
    addMessage('system', 'Захват остановлен: ' + error.message);
    void stopMic();
  };
  if (!task) fail(new Error('аудиоканал не успевает принимать звук'), 'upload_backpressure');
  else task.catch(fail);
}

function voiceCaptureDiagnostic(mic, reason, error) {
  if (typeof CustomEvent !== 'function' || typeof window.dispatchEvent !== 'function') return;
  const contextState = mic.context?.state;
  const errorName = error?.name;
  const age = performance.now() - mic.lastFrameAt;
  const detail = {
    schema_version: 1, reason,
    error_name: ['TypeError', 'AbortError', 'TimeoutError', 'Error'].includes(errorName) ? errorName : 'unknown',
    status: Number.isInteger(error?.status) && error.status >= 100 && error.status <= 599 ? error.status : null,
    context_state: ['running', 'suspended', 'closed'].includes(contextState) ? contextState : 'unknown',
    track_states: mic.stream.getAudioTracks().slice(0, 4).map(track =>
      ['live', 'ended'].includes(track.readyState) ? track.readyState : 'unknown'),
    upload_pending: Math.max(0, Math.min(6, mic.uploadQueue.pending)),
    worklet_chunks: mic.workletChunks || 0,
    last_frame_age_ms: Number.isFinite(age) ? Math.max(0, Math.min(3600000, Math.round(age))) : null,
    active: Boolean(mic.active), finalizing: Boolean(mic.finalizing),
  };
  try { window.dispatchEvent(new CustomEvent('jawl-voice-capture', {detail})); }
  catch { /* diagnostics must not prevent capture teardown */ }
}

function enqueueMicOperation(mic, operation, bounded = false) {
  const queue = mic.uploadQueue;
  if (bounded && queue.pending >= 6) return null;
  if (bounded) queue.pending += 1;
  const task = queue.tail.catch(() => {}).then(() => mic.active ? operation() : undefined);
  queue.tail = task.then(() => undefined, () => undefined).finally(() => {
    if (bounded) queue.pending -= 1;
  });
  return task;
}

function finalizeAfterMicUploads(mic, finalize) {
  const previousUploads = mic.uploadQueue.tail;
  mic.uploadQueue = {tail: Promise.resolve(), pending: 0};
  return previousUploads.catch(() => {}).then(() => mic.active ? finalize() : null);
}

function micTurnIsCurrent(mic, generation) {
  return Boolean(mic.active && state.mic === mic && mic.turnGeneration === generation);
}

function newVoiceUtterance() {
  const id = `${Date.now()}-${++state.voiceSequence}`;
  return {sessionId: `app-mic-${id}`, correlationId: `turn-voice-${id}`};
}

async function finishUtterance() {
  const mic = state.mic;
  if (!mic || mic.finalizing || !mic.heard) return;
  mic.finalizing = true;
  mic.drafts?.finalize();
  const lastVoiceAt = mic.inputGate.lastVoiceAt;
  mic.flushDestination = mic.utterance;
  const turnGeneration = mic.turnGeneration;
  micState.textContent = 'Распознаю…';
  try {
    await flushMicWorklet(mic);
    if (!micTurnIsCurrent(mic, turnGeneration)) return;
    const boundary = mic.helpers.completeMicFlushBoundary(mic, lastVoiceAt, newVoiceUtterance());
    if (boundary.resumed) return;
    const utterance = boundary.utterance;
    state.voiceSessionId = mic.utterance.sessionId;
    state.voiceCorrelationId = mic.utterance.correlationId;
    const data = await finalizeAfterMicUploads(mic, async () => {
      const response = await fetch('/api/voice/end', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify({
        session_id: utterance.sessionId,
        correlation_id: utterance.correlationId,
        owner: 'desktop',
        capture_id: mic.lease.leaseId,
      }),
      signal: mic.abortController.signal,
      });
      mic.helpers.requireVoiceResponseOk(response, 'voice/end');
      return response.json();
    });
    if (!data || !micTurnIsCurrent(mic, turnGeneration)) return;
    if (data.transcript) addMessage('user', data.transcript);
    const answers = data.responses || [];
    const last = answers[answers.length - 1];
    if (last) handleEnvelope(last);
    else if (data.error) addMessage('system', 'Голос: ' + data.error);
  } catch (error) {
    if (micTurnIsCurrent(mic, turnGeneration)) {
      addMessage('system', 'Голосовой ход не завершился: ' + error.message);
      await stopMic();
    }
  } finally {
    if (state.mic === mic && mic.active) {
      mic.flushDestination = null;
      mic.finalizing = false;
      mic.drafts?.reset();
      mic.drafts?.resume();
      micState.textContent = state.micActive ? 'Микрофон включён — говорите.' : 'Микрофон выключен.';
    }
  }
}

function flushMicWorklet(mic) {
  if (!mic.active || !mic.gate?.port) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = (flushed = true) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const index = mic.flushWaiters.indexOf(done);
      if (index >= 0) mic.flushWaiters.splice(index, 1);
      if (flushed) resolve();
      else reject(new Error('AudioWorklet не подтвердил границу реплики'));
    };
    const timer = setTimeout(() => done(false), 500);
    mic.flushWaiters.push(done);
    mic.gate.port.postMessage({type: 'flush'});
  });
}

async function stopMic() {
  const stopGeneration = ++micStartGeneration;
  micStarting = false;
  const mic = state.mic;
  const pendingLease = pendingCaptureLease;
  pendingCaptureLease = null;
  state.mic = null;
  state.micActive = false;
  cancelSpeechPlayback();
  chatMic.style.background = '';
  micState.textContent = 'Микрофон выключен.';
  if (mic) {
    mic.active = false;
    clearInterval(mic.draftPoll);
    mic.drafts?.stop();
    mic.abortController.abort();
    clearInterval(mic.poll);
    mic.stream.getTracks().forEach(t => t.stop());
    mic.flushWaiters.splice(0).forEach(done => done());
    await Promise.allSettled([mic.context.close(), mic.lease?.release(), pendingLease?.release()]);
  } else {
    await pendingLease?.release();
  }
  if (micStartGeneration === stopGeneration) micState.textContent = 'Микрофон выключен.';
}

// ---------------------------------------------------------------------------
// wardrobe
// ---------------------------------------------------------------------------

async function loadWardrobe() {
  const grid = document.querySelector('#wardrobe-grid');
  if (!grid) return;
  try {
    const r = await fetch('/api/avatar/wardrobe', {credentials: 'include', headers: API.headers()});
    const w = await r.json();
    grid.replaceChildren();
    for (const model of (w.models || [])) {
      const tile = document.createElement('div');
      tile.className = 'model-tile' + (window.__jawlScene?.wornModel === model.model ? ' worn' : '');
      tile.innerHTML = `<div class="em">🧍</div><div class="nm">${model.model}</div>` +
                       `<div class="sz">${(model.size_bytes / 1048576).toFixed(1)} МБ</div>`;
      tile.addEventListener('click', async () => {
        tile.textContent = 'надеваю…';
        await window.__jawlScene?.wear(model.model);
        loadWardrobe();
      });
      grid.appendChild(tile);
    }
    if (!w.count) grid.textContent = 'гардероб пуст — положи .vrm в runtime/vrm-models';
  } catch { grid.textContent = 'гардероб недоступен'; }
}
window.loadWardrobe = loadWardrobe;

document.querySelectorAll('[data-emotion]').forEach(button => {
  button.addEventListener('click', () => {
    window.__jawlScene?.setEmotion(button.dataset.emotion);
    setVal('avatar-current', button.dataset.emotion);
  });
});

// ---------------------------------------------------------------------------
// TTS preview
// ---------------------------------------------------------------------------

document.querySelector('#tts-preview')?.addEventListener('click', () => {
  const text = document.querySelector('#tts-preview-text')?.value.trim();
  if (text) void speakFinal({text});
});

// ---------------------------------------------------------------------------
// system
// ---------------------------------------------------------------------------

document.querySelector('#jawl-restart')?.addEventListener('click', async () => {
  if (!confirm('Перезапустить JAWL-агента?')) return;
  try {
    const r = await fetch('/api/jawl/restart', {method: 'POST', credentials: 'include', headers: API.headers(), body: '{}'});
    const d = await r.json();
    addMessage('system', 'JAWL: ' + (d.status || 'перезапуск запущен'));
  } catch (e) { alert('Не удалось: ' + e.message); }
});

document.querySelector('#jawl-logs')?.addEventListener('click', async () => {
  const el = document.querySelector('#jawl-log');
  el.hidden = !el.hidden;
  if (!el.hidden) {
    try {
      el.textContent = await (await fetch('/api/logs/agent?tail=40', {credentials: 'include'})).text();
    } catch { el.textContent = 'логи недоступны'; }
  }
});

document.querySelector('#emergency-stop')?.addEventListener('click', async () => {
  if (!confirm('Аварийный стоп всей активности агента?')) return;
  try {
    await fetch('/api/emergency-stop', {method: 'POST', credentials: 'include', headers: API.headers(), body: '{}'});
    addMessage('system', 'Аварийный стоп выполнен.');
  } catch (e) { alert('Не удалось: ' + e.message); }
});

// ---------------------------------------------------------------------------
// go
// ---------------------------------------------------------------------------

boot();
startRefresh();
loadWardrobe();
refreshMicDevices();
if (typeof loadSettings === 'function') loadSettings();
