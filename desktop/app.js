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
};

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
  window.__jawlScene?.setEmotion(envelope.emotion?.id || 'neutral');
  setVal('avatar-current', envelope.emotion?.id || 'neutral');
  if (speak && envelope.speak !== false && envelope.text) speakFinal(envelope);
}

async function sendChat() {
  const text = chatInput.value.trim();
  if (!text || state.thinking) return;
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
async function speakFinal(envelope) {
  try {
    const response = await fetch('/api/tts/stream', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({text: envelope.text}),
    });
    if (!response.ok) return;
    const blob = await response.blob();
    const audio = new Audio(URL.createObjectURL(blob));
    if (!lipContext) lipContext = new AudioContext();
    if (lipContext.state === 'suspended') await lipContext.resume();
    const source = lipContext.createMediaElementSource(audio);
    const analyser = lipContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser).connect(lipContext.destination);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const pump = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
      window.__jawlScene?.setLipLevel(Math.sqrt(sum / data.length) * 2.2);
      if (!audio.ended) requestAnimationFrame(pump);
      else window.__jawlScene?.setLipLevel(0);
    };
    audio.onplay = pump;
    audio.onended = () => window.__jawlScene?.setLipLevel(0);
    await audio.play();
  } catch { /* voice is optional; text stays */ }
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

chatMic.addEventListener('click', () => { state.micActive ? stopMic() : startMic(); });

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
  try {
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
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    const context = new AudioContext();
    await context.audioWorklet.addModule('/mic-processor.js');
    const source = context.createMediaStreamSource(stream);
    const gate = new AudioWorkletNode(context, 'jawl-mic-processor');
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(gate);
    source.connect(analyser);

    const track = stream.getAudioTracks()[0];
    setVal('mic-device', track?.label || '—');
    // labels are visible now: refresh the picker with real names
    refreshMicDevices();

    state.voiceSessionId = `app-mic-${Date.now()}`;
    state.voiceCorrelationId = `turn-voice-${Date.now()}`;
    state.mic = {stream, context, gate, analyser, lastLoud: performance.now(), sending: false, pending: 0};

    gate.port.onmessage = (event) => {
      if (!(event.data instanceof ArrayBuffer)) return;
      const samples = new Float32Array(event.data);
      uploadChunk(samples, context.sampleRate);
    };

    const data = new Uint8Array(analyser.frequencyBinCount);
    state.mic.poll = setInterval(() => {
      if (!state.mic) return;
      analyser.getByteTimeDomainData(data);
      let energy = 0;
      for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; energy += v * v; }
      const rms = Math.sqrt(energy / data.length);
      if (rms > 0.02) {
        state.mic.lastLoud = performance.now();
        state.mic.heard = true;
        micState.textContent = 'Слушаю…';
      } else if (state.mic.heard && performance.now() - state.mic.lastLoud > 2000) {
        finishUtterance();
      }
    }, 200);

    state.micActive = true;
    chatMic.style.background = 'var(--accent)';
    micState.textContent = 'Микрофон включён — говорите.';
    setVal('mic-state', 'Микрофон включён.');
  } catch (error) {
    micState.textContent = 'Микрофон недоступен: ' + error.message;
  }
}

async function uploadChunk(samples, sampleRate) {
  const mic = state.mic;
  if (!mic || mic.finalizing) return;
  if (mic.pending > 6) return; // bounded backpressure
  mic.pending += 1;
  try {
    const payload = {
      session_id: state.voiceSessionId,
      correlation_id: state.voiceCorrelationId,
      sample_rate: 16000,
      channels: 1,
      pcm16_base64: pcm16Base64(downsample(samples, sampleRate, 16000)),
    };
    await fetch('/api/voice/audio', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify(payload),
    });
  } catch { /* a dropped chunk is not fatal: the utterance continues */ }
  finally { if (state.mic) state.mic.pending -= 1; }
}

async function finishUtterance() {
  const mic = state.mic;
  if (!mic || mic.finalizing) return;
  mic.finalizing = true;
  micState.textContent = 'Распознаю…';
  try {
    const response = await fetch('/api/voice/end', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify({session_id: state.voiceSessionId, correlation_id: state.voiceCorrelationId}),
    });
    const data = await response.json();
    if (data.transcript) addMessage('user', data.transcript);
    const answers = data.responses || [];
    const last = answers[answers.length - 1];
    if (last) handleEnvelope(last);
    else if (data.error) addMessage('system', 'Голос: ' + data.error);
    // a fresh session for the next utterance
    state.voiceSessionId = `app-mic-${Date.now()}`;
    state.voiceCorrelationId = `turn-voice-${Date.now()}`;
    mic.heard = false;
  } catch (error) {
    addMessage('system', 'Голосовой ход не завершился: ' + error.message);
  } finally {
    if (state.mic) state.mic.finalizing = false;
    micState.textContent = state.micActive ? 'Микрофон включён — говорите.' : 'Микрофон выключен.';
  }
}

async function stopMic() {
  const mic = state.mic;
  state.mic = null;
  state.micActive = false;
  chatMic.style.background = '';
  if (mic) {
    clearInterval(mic.poll);
    mic.stream.getTracks().forEach(t => t.stop());
    await mic.context.close().catch(() => {});
  }
  micState.textContent = 'Микрофон выключен.';
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

document.querySelector('#tts-preview')?.addEventListener('click', async () => {
  const text = document.querySelector('#tts-preview-text').value.trim();
  const audio = document.querySelector('#tts-audio');
  if (!text) return;
  try {
    const response = await fetch('/api/tts/synthesize', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify({text}),
    });
    if (!response.ok) throw new Error('tts status ' + response.status);
    audio.src = URL.createObjectURL(await response.blob());
    audio.play();
  } catch (e) { audio.removeAttribute('src'); alert('Превью не удалось: ' + e.message); }
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