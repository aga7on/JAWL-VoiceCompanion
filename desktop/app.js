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
  speechErrorNoticeKey: null,
};
let micStartGeneration = 0;
let micStarting = false;
function setMicButtonState(pressed, busy = false) {
  for (const button of document.querySelectorAll('#chat-mic, #hud-mic')) {
    button.setAttribute('aria-pressed', String(Boolean(pressed)));
    if (busy) button.setAttribute('aria-busy', 'true');
    else button.removeAttribute('aria-busy');
  }
}
function announceMicStatus(text) {
  const status = document.querySelector('#mic-live-status');
  if (status) status.textContent = text;
}
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
    if (typeof URLSearchParams === 'function' && new URLSearchParams(globalThis.location?.search || '').get('openConsole') === '1') {
      globalThis.location.replace('/console/');
      return;
    }
    setConn('ok', '\u041f\u0430\u043d\u0435\u043b\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0430');
    refreshAll();
  } catch {
    setConn('err', '\u0421\u0435\u0440\u0432\u0435\u0440 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d');
  }
}

let managedProfileStopPending = false;
async function requestManagedProfileStop() {
  if (managedProfileStopPending) return;
  managedProfileStopPending = true;
  try {
    const response = await fetch('/api/profile/stop', {
      method: 'POST', credentials: 'include', headers: API.headers(), body: '{}',
    });
    const result = await response.json().catch(() => ({}));
    if (response.status !== 202 || result.status !== 'stop_requested') {
      managedProfileStopPending = false;
      setConn('err', result.error || 'Managed profile stop was not accepted', {announce: true});
      return;
    }
    setConn('ok', '\u0417\u0430\u043f\u0440\u043e\u0441 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d; \u0436\u0434\u0443 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f \u043b\u0430\u0443\u043d\u0447\u0435\u0440\u0430', {announce: true});
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      const statusResponse = await fetch('/api/profile/stop/status', {
        credentials: 'include', cache: 'no-store', headers: API.headers(),
      });
      if (!statusResponse.ok) continue;
      const status = await statusResponse.json().catch(() => ({}));
      if (status.status === 'stopping' && status.request_id === result.request_id) {
        setConn('ok', '\u041b\u0430\u0443\u043d\u0447\u0435\u0440 \u043f\u0440\u0438\u043d\u044f\u043b \u043e\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0443; \u0441\u043b\u0443\u0436\u0431\u044b \u0437\u0430\u0432\u0435\u0440\u0448\u0430\u044e\u0442\u0441\u044f', {announce: true});
        window.jawlDesktop?.acknowledgeProfileStop?.();
        return;
      }
    }
    managedProfileStopPending = false;
    setConn('err', '\u041b\u0430\u0443\u043d\u0447\u0435\u0440 \u043d\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u043b \u043e\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0443; \u043f\u0440\u043e\u0444\u0438\u043b\u044c \u043c\u043e\u0436\u0435\u0442 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0442\u044c \u0440\u0430\u0431\u043e\u0442\u0443', {announce: true});
  } catch {
    managedProfileStopPending = false;
    setConn('err', 'Managed profile stop request failed', {announce: true});
  }
}

window.jawlDesktop?.onProfileStopRequest?.(() => { void requestManagedProfileStop(); });

function setConn(kind, text, options) {
  const announce = Boolean(options?.announce);
  const dot = document.querySelector('#conn-dot');
  const label = document.querySelector('#conn-status');
  dot.className = 'dot ' + (kind === 'ok' ? 'ok' : kind === 'err' ? 'err' : '');
  label.textContent = text;
  const feedback = document.querySelector('#connection-feedback');
  if (feedback) {
    if (announce) {
      feedback.dataset.pinned = 'true';
      feedback.textContent = text;
      feedback.hidden = false;
      feedback.classList.toggle('error', kind === 'err');
    } else if (feedback.dataset.pinned !== 'true') {
      const visibleFeedback = kind === 'err';
      feedback.textContent = visibleFeedback ? text : '';
      feedback.hidden = !visibleFeedback;
      feedback.classList.toggle('error', kind === 'err');
    }
  }
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

const DOCTOR_LABELS = {
  jawl: 'JAWL', voicemem: 'VoiceMem', asr: 'GigaAM ASR', tts: 'OmniVoice TTS',
  vision: 'Зрение', avatar: 'Аватар', hostos: 'HostOS',
  ambient_memory: 'Ambient-память', ambient_audio: 'Системный звук',
  resources: 'Ресурсы', streaming_asr: 'Streaming ASR', sensory_ingest: 'Сенсорика',
};
const DOCTOR_STATUS = {
  connected: 'подключено', online: 'онлайн', ready: 'готово', ok: 'работает',
  gigaam: 'GigaAM', desktop: 'в приложении', live: 'live',
  dry_run: 'dry-run · безопасно', configured: 'настроено, не активно',
  disabled: 'выключено', idle: 'ожидает', stopped: 'остановлено',
  mock: 'текстовый mock', not_configured: 'не настроено', offline: 'не запущено',
  degraded: 'деградация', error: 'ошибка',
};
const DOCTOR_ICON = {ok: 'OK', off: 'OFF', warn: '!', error: 'ERR'};

function renderDoctor(report) {
  const el = document.querySelector('#doctor-log');
  if (!el) return;
  const checks = report?.checks || [];
  el.replaceChildren();
  if (!checks.length) { el.textContent = '—'; return; }
  const active = checks.filter(c => c.state === 'ok').length;
  const attention = checks.filter(c => c.state === 'warn' || c.state === 'error').length;
  const summary = document.createElement('div');
  summary.className = 'doctor-summary';
  summary.textContent = attention
    ? `активно ${active} · требуют внимания ${attention}`
    : `активно ${active} · всё в порядке`;
  el.appendChild(summary);
  for (const check of checks) {
    const row = document.createElement('div');
    row.className = 'doctor-row ' + (check.state || (check.ready ? 'ok' : 'off'));
    if (check.summary) row.title = check.summary;
    const icon = document.createElement('span');
    icon.className = 'doctor-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = DOCTOR_ICON[check.state] || 'OFF';
    const name = document.createElement('span');
    name.className = 'doctor-name';
    name.textContent = DOCTOR_LABELS[check.id] || check.id;
    const status = document.createElement('span');
    status.className = 'doctor-status';
    status.textContent = DOCTOR_STATUS[check.status] || check.status;
    row.append(icon, name, status);
    el.appendChild(row);
  }
}

async function refreshStatuses() {
  try {
    const d = await (await fetch('/api/doctor', {credentials: 'include'})).json();
    const checks = {};
    (d.checks || []).forEach(c => { checks[c.id] = c; });
    setVal('svc-brain', checks.jawl ? checks.jawl.status : '—');
    setVal('svc-jawl', checks.jawl?.ready ? 'готов' : (checks.jawl?.status || '—'));
    const jawlActivity = await (await fetch('/api/jawl/activity', {
      credentials: 'include', cache: 'no-store', headers: API.headers(),
    })).json().catch(() => null);
    const activityNode = document.querySelector('#svc-jawl-activity');
    if (activityNode) {
      if (jawlActivity?.configured && jawlActivity.running) {
        const phase = jawlActivity.phase || 'unknown';
        const active = !['sleep', 'idle', 'off'].includes(phase);
        activityNode.textContent = active
          ? `JAWL работает · ${phase}${jawlActivity.step ? ` · шаг ${jawlActivity.step}` : ''}${jawlActivity.model ? ` · ${jawlActivity.model}` : ''}`
          : `JAWL запущен и ожидает события${jawlActivity.model ? ` · ${jawlActivity.model}` : ''}`;
      } else if (jawlActivity?.configured) {
        activityNode.textContent = 'JAWL остановлен';
      } else {
        activityNode.textContent = 'Текущая работа JAWL недоступна';
      }
    }
      setVal('svc-panel', '\u041f\u0430\u043d\u0435\u043b\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0430');
    const ts = await (await fetch('/api/tts/status', {credentials: 'include'})).json();
    setVal('tts-provider', ts.model || ts.provider || '—');
    setVal('tts-status', ts.status || '—');
    setVal('svc-tts', ts.status || '—');
    renderDoctor(d);
    // ASR status: is the voice lane armed?
    const vs = await (await fetch('/api/voice/status', {credentials: 'include'})).json().catch(() => ({}));
    setVal('asr-status', vs.asr || vs.streaming_asr || (vs.configured ? 'настроен' : 'выключен'));
    const att = await (await fetch('/api/attention', {credentials: 'include'})).json().catch(() => ({}));
    if (typeof att.dnd === 'boolean') {
      dndActive = att.dnd;
      setVal('proactive-state', dndActive ? 'Не беспокоить (DND)' : 'включён');
      setVal('quiet-state', att.quiet_hours || 'нет');
      syncHudToggles();
    }
    const amb = await (await fetch('/api/ambient-memory', {credentials: 'include', headers: API.headers()})).json().catch(() => ({}));
    if (typeof amb?.state?.enabled === 'boolean') {
      sensesActive = amb.state.enabled;
      setVal('ambient-state', amb.state.paused ? 'пауза' : (sensesActive ? `активна (${amb.state.observation_count || 0})` : 'выключена'));
      syncHudToggles();
    }
    const shell = await (await fetch('/api/shell/status', {
      credentials: 'include', headers: API.headers(), cache: 'no-store',
    })).json().catch(() => ({}));
    renderSensoryHealth(shell);
  } catch {
    setConn('err', '\u0421\u0435\u0440\u0432\u0435\u0440 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d');
  }
}

function renderSensoryHealth(shell) {
  const summary = document.querySelector('#sensory-health');
  if (shell?.ok !== true) {
    for (const id of ['sensor-mic', 'sensor-screen', 'sensor-loopback', 'sensor-attention']) {
      const element = document.querySelector(`#${id}`);
      if (!element) continue;
      element.textContent = 'статус недоступен';
      element.dataset.state = 'error';
    }
    const loopbackDeviceElement = document.querySelector('#sensor-loopback-device');
    if (loopbackDeviceElement) loopbackDeviceElement.textContent = 'Статус источника недоступен';
    const ambientAsrElement = document.querySelector('#sensor-asr-status');
    if (ambientAsrElement) {
      ambientAsrElement.textContent = 'Статус ASR системного звука недоступен';
      ambientAsrElement.dataset.state = 'error';
    }
    const historyElement = document.querySelector('#sensor-history-status');
    if (historyElement) {
      historyElement.textContent = 'Статус сенсорной истории недоступен';
      historyElement.dataset.state = 'error';
    }
    const soundscapeElement = document.querySelector('#sensor-soundscape-status');
    if (soundscapeElement) soundscapeElement.textContent = 'Статус музыкального анализатора недоступен';
    const audioDescriptionElement = document.querySelector('#sensor-audio-description-status');
    if (audioDescriptionElement) {
      audioDescriptionElement.textContent = 'Статус описателя системного звука недоступен';
      audioDescriptionElement.dataset.state = 'error';
    }
    if (summary) {
      summary.textContent = 'Статус сенсоров недоступен';
      summary.dataset.state = 'error';
    }
    const compactSummary = document.querySelector('#sensory-health-compact');
    if (compactSummary) {
      compactSummary.textContent = 'Сенсоры недоступны';
      compactSummary.dataset.state = 'error';
    }
    return;
  }
  const capture = shell?.capture || {};
  const visual = shell?.visual || {};
  const screen = shell?.screen || {};
  const attention = shell?.attention || {};
  const micOwner = capture.microphone_owner;
  const mic = state.micActive || micOwner
    ? `включён${micOwner === 'native' ? ' (задача)' : ''}`
    : 'выключен';
  const visualRunning = Boolean(visual.running);
  const screenRunning = Boolean(visualRunning || screen.running);
  const age = typeof visual.latest_age_ms === 'number' && Number.isFinite(visual.latest_age_ms)
    ? visual.latest_age_ms
    : null;
  const captionAge = typeof visual.caption_age_ms === 'number' && Number.isFinite(visual.caption_age_ms)
    ? visual.caption_age_ms
    : age;
  const confirmedAge = typeof visual.caption_confirmed_age_ms === 'number' && Number.isFinite(visual.caption_confirmed_age_ms)
    ? visual.caption_confirmed_age_ms
    : null;
  const captionFresh = visual.caption_fresh === true;
  const screenLabel = !screenRunning
    ? 'выключен'
    : !visualRunning
      ? 'наблюдатель активен'
    : visual.error_active
      ? 'ошибка захвата'
    : age === null
      ? 'ждёт описание'
      : !captionFresh || ((confirmedAge ?? captionAge) !== null && (confirmedAge ?? captionAge) > 6000)
        ? `описание устарело, ${Math.round((captionAge ?? age) / 1000)} с`
        : confirmedAge !== null
          ? `описание подтверждено, ${Math.round(confirmedAge / 1000)} с · модель ${Math.round((captionAge ?? 0) / 1000)} с`
          : `описание актуально, ${Math.round((captionAge ?? age) / 1000)} с`;
  const loopbackAge = typeof capture.loopback_last_chunk_age_ms === 'number' && Number.isFinite(capture.loopback_last_chunk_age_ms)
    ? capture.loopback_last_chunk_age_ms
    : null;
  const loopbackSignalState = ['digital_silence', 'nonzero_pcm_unclassified'].includes(capture.loopback_signal_window_state)
    ? capture.loopback_signal_window_state
    : 'unknown';
  const loopback = !capture.loopback_configured
    ? '\u043d\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043d'
    : capture.loopback_paused
      ? '\u043f\u0430\u0443\u0437\u0430'
      : capture.loopback_running
        ? loopbackAge === null
          ? '\u043f\u043e\u0442\u043e\u043a \u0437\u0430\u043f\u0443\u0449\u0435\u043d, \u0436\u0434\u0451\u0442 \u0434\u0430\u043d\u043d\u044b\u0435'
          : loopbackAge > 3000
            ? `\u043d\u0435\u0442 \u043d\u043e\u0432\u044b\u0445 \u0447\u0430\u043d\u043a\u043e\u0432, ${Math.round(loopbackAge / 1000)} \u0441`
            : loopbackSignalState === 'digital_silence'
              ? '\u0437\u0430\u0445\u0432\u0430\u0442 \u0430\u043a\u0442\u0438\u0432\u0435\u043d: \u0446\u0438\u0444\u0440\u043e\u0432\u044b\u0435 \u043d\u0443\u043b\u0438'
              : loopbackSignalState === 'nonzero_pcm_unclassified'
                ? 'PCM \u043f\u043e\u0441\u0442\u0443\u043f\u0430\u0435\u0442, \u0437\u0432\u0443\u043a \u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d'
                : '\u0443\u0440\u043e\u0432\u0435\u043d\u044c \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d'
        : capture.loopback_error
          ? '\u043e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u0445\u0432\u0430\u0442\u0430'
          : capture.loopback_enabled
            ? '\u043e\u0436\u0438\u0434\u0430\u0435\u0442 \u0437\u0430\u043f\u0443\u0441\u043a'
            : '\u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d';
  const loopbackDeviceName = typeof capture.loopback_device === 'string' ? capture.loopback_device.trim() : '';
  const loopbackDeviceIndex = Number.isInteger(capture.loopback_device_index) ? capture.loopback_device_index : null;
  const loopbackHostApiIndex = Number.isInteger(capture.loopback_host_api_index) ? capture.loopback_host_api_index : null;
  const loopbackRate = Number.isFinite(capture.loopback_sample_rate) ? Math.round(capture.loopback_sample_rate / 1000) : null;
  const loopbackChannels = Number.isInteger(capture.loopback_channels) ? capture.loopback_channels : null;
  const loopbackSource = !capture.loopback_configured
    ? 'Источник не настроен'
    : capture.loopback_paused
      ? 'Захват приостановлен'
      : !capture.loopback_running
        ? capture.loopback_enabled ? 'Ожидает запуска захвата' : 'Захват выключен'
        : !loopbackDeviceName
          ? 'Устройство вывода не определено'
          : `Устройство: ${loopbackDeviceName}${loopbackHostApiIndex !== null || loopbackDeviceIndex !== null ? ` · WASAPI ${loopbackHostApiIndex ?? '—'} / ${loopbackDeviceIndex ?? '—'}` : ''}${loopbackRate !== null ? ` · ${loopbackRate} кГц` : ''}${loopbackChannels !== null ? ` · ${loopbackChannels} канала` : ''}`;
  const initiative = attention.dnd
    ? 'не беспокоить'
    : attention.quiet_hours_active
      ? 'тихие часы'
      : 'разрешена';
  const rows = [
    ['sensor-mic', mic, mic === 'выключен' ? 'off' : 'ok'],
    ['sensor-screen', screenLabel, visualRunning && visual.error_active ? 'error' : visualRunning && (age === null || !captionFresh || (captionAge !== null && captionAge > 6000)) ? 'warn' : screenRunning ? 'ok' : 'off'],
    ['sensor-loopback', loopback, capture.loopback_error ? 'error' : capture.loopback_running && loopbackAge !== null && loopbackAge <= 3000 && loopbackSignalState === 'nonzero_pcm_unclassified' ? 'warn' : capture.loopback_running ? 'warn' : 'off'],
    ['sensor-attention', initiative, attention.dnd || attention.quiet_hours_active ? 'off' : 'ok'],
  ];
  for (const [id, label, status] of rows) {
    const element = document.querySelector(`#${id}`);
    if (!element) continue;
    element.textContent = label;
    element.dataset.state = status;
  }
  const loopbackDeviceElement = document.querySelector('#sensor-loopback-device');
  if (loopbackDeviceElement) loopbackDeviceElement.textContent = loopbackSource;
  const ambientAsrElement = document.querySelector('#sensor-asr-status');
  if (ambientAsrElement) {
    const mode = String(capture.ambient_asr_mode || '');
    const transcriptCount = Number.isFinite(capture.ambient_asr_transcripts)
      ? Math.max(0, Math.round(capture.ambient_asr_transcripts)) : 0;
    const filteredCount = Number.isFinite(capture.ambient_asr_noise_filtered)
      ? Math.max(0, Math.round(capture.ambient_asr_noise_filtered)) : 0;
    const transcriptAge = Number.isFinite(capture.ambient_asr_last_age_ms)
      ? Math.max(0, Math.round(capture.ambient_asr_last_age_ms)) : null;
    const transcriptFresh = capture.ambient_asr_last_fresh === true
      && transcriptAge !== null && transcriptAge <= 120000;
    const asrName = mode === 'external_final_utterance' ? 'GigaAM ASR'
      : mode === 'voicemem_streaming' ? 'VoiceMem stream' : 'Loopback ASR';
    const asrStatus = !mode ? 'не подключён'
      : capture.loopback_paused ? 'захват приостановлен'
        : !capture.loopback_running ? 'ожидает запуска захвата'
          : transcriptFresh ? `есть результат · ${Math.round(transcriptAge / 1000)} с назад`
            : transcriptAge !== null ? `последняя расшифровка ${Math.round(transcriptAge / 1000)} с назад`
              : transcriptCount > 0 ? 'ожидает следующую речевую реплику'
                : 'ожидает первую речевую реплику';
    const stats = [`${transcriptCount} фрагм.`, filteredCount ? `отфильтровано ${filteredCount}` : '']
      .filter(Boolean).join(' · ');
    ambientAsrElement.textContent = `${asrName}: ${asrStatus} · ${stats}`;
    ambientAsrElement.dataset.state = !mode || capture.loopback_paused || !capture.loopback_running
      ? 'off' : transcriptFresh ? 'ok' : transcriptAge !== null ? 'warn' : 'off';
  }
  const historyElement = document.querySelector('#sensor-history-status');
  if (historyElement) {
    const history = capture.sensory_history && typeof capture.sensory_history === 'object'
      ? capture.sensory_history : null;
    const writes = history?.writes && typeof history.writes === 'object' ? history.writes : {};
    const countStatus = (suffix) => Object.entries(writes)
      .filter(([key]) => key.endsWith(`:${suffix}`))
      .reduce((sum, [, value]) => sum + (Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0), 0);
    const recorded = countStatus('recorded');
    const coalesced = countStatus('coalesced');
    const writeErrors = Number.isFinite(history?.write_errors) ? Math.max(0, Math.round(history.write_errors)) : 0;
    const lastStatus = String(history?.last_status || '');
    const lastModality = String(history?.last_modality || '');
    const persistence = history?.persistence && typeof history.persistence === 'object'
      ? history.persistence : null;
    const flushAge = Number.isFinite(persistence?.last_flush_age_seconds)
      ? Math.max(0, Math.round(persistence.last_flush_age_seconds)) : null;
    const persistenceError = String(persistence?.last_error || '');
    const errorStage = String(persistence?.last_error_stage || '');
    const persistenceErrorLabel = errorStage === 'load' ? 'архив не загружен'
      : errorStage === 'clear' ? 'ошибка очистки'
        : errorStage === 'telemetry' ? 'ошибка телеметрии'
          : 'ошибка записи';
    const flushText = persistenceError
      ? `${persistenceErrorLabel}: ${persistenceError}`
      : flushAge !== null ? `flush ${flushAge} с назад`
        : recorded + coalesced > 0 ? 'ожидает первого flush' : 'flush ещё не выполнялся';
    const historyText = !history || history.configured !== true
      ? 'сенсорный архив не подключён'
      : history.persistence?.enabled === false || lastStatus === 'disabled'
        ? 'сенсорный архив выключен'
        : `${recorded} записано · ${coalesced} объединено · ${writeErrors} ошибок`
          + (lastStatus ? ` · последнее: ${lastModality || 'сенсор'} ${lastStatus}` : ' · ожидает наблюдения')
          + ` · ${flushText}`;
    historyElement.textContent = `История: ${historyText}`;
    historyElement.dataset.state = !history || history.configured !== true || lastStatus === 'disabled'
      || history.persistence?.enabled === false
      ? 'off' : persistenceError || lastStatus === 'error' ? 'error'
        : writeErrors > 0 || (recorded + coalesced > 0 && flushAge === null) ? 'warn' : 'ok';
  }
  const soundscapeElement = document.querySelector('#sensor-soundscape-status');
  if (soundscapeElement) {
    const soundscapeCount = Number.isFinite(capture.soundscape_count) ? Math.max(0, Math.round(capture.soundscape_count)) : 0;
    const soundscapeErrors = Number.isFinite(capture.soundscape_errors) ? Math.max(0, Math.round(capture.soundscape_errors)) : 0;
    const soundscapeP95 = Number.isFinite(capture.soundscape_latency_ms_p95) ? `· p95 ${Math.round(capture.soundscape_latency_ms_p95)} ms` : '';
    const soundscapeAge = Number.isFinite(capture.soundscape_last_age_ms)
      ? Math.max(0, Math.round(capture.soundscape_last_age_ms))
      : null;
    const soundscapeFresh = capture.soundscape_last_fresh === true && soundscapeAge !== null && soundscapeAge <= 20000;
    const soundscapeTags = Array.isArray(capture.soundscape_last_tags)
      ? capture.soundscape_last_tags.filter(tag => typeof tag === 'string' && tag.trim()).slice(0, 2)
      : [];
    const soundscapeAgeText = soundscapeAge === null ? '' : `${Math.round(soundscapeAge / 1000)} с назад`;
    const soundscapeStatus = !capture.soundscape_configured
      ? 'Анализатор музыки не подключён'
      : capture.loopback_paused
        ? 'Анализ системного звука приостановлен'
        : !capture.loopback_running
          ? 'Анализатор готов; захват системного звука не запущен'
          : soundscapeFresh && capture.soundscape_last_kind === 'music'
            ? `Музыка обнаружена${soundscapeTags.length ? ` · повторяющийся тег: ${soundscapeTags.join(', ')}` : ''} · ${soundscapeAgeText}`
            : soundscapeFresh
              ? `Свежая проверка: музыка не подтверждена · ${soundscapeAgeText}`
              : soundscapeAge !== null
                ? `Нет свежей оценки музыки · последняя ${soundscapeAgeText}`
                : soundscapeCount > 0
                  ? 'Ожидает следующего аудиосегмента'
                  : 'Ожидает первого аудиосегмента';
    const soundscapeStats = [`${soundscapeCount} сегм.`, soundscapeP95.replace(/^·\s*/, ''), soundscapeErrors ? `ошибок ${soundscapeErrors}` : '']
      .filter(Boolean)
      .join(' · ');
    soundscapeElement.textContent = `YAMNet CPU: ${soundscapeStatus} · ${soundscapeStats}`;
    soundscapeElement.dataset.state = !capture.soundscape_configured || capture.loopback_paused || !capture.loopback_running
      ? 'off'
      : soundscapeFresh && capture.soundscape_last_kind === 'music'
        ? 'ok'
        : soundscapeFresh
          ? 'off'
          : soundscapeErrors > 0 && soundscapeAge === null
            ? 'error'
            : 'warn';
  }
  const audioDescriptionElement = document.querySelector('#sensor-audio-description-status');
  if (audioDescriptionElement) {
    const descriptionCount = Number.isFinite(capture.audio_description_count) ? Math.max(0, Math.round(capture.audio_description_count)) : 0;
    const descriptionErrors = Number.isFinite(capture.audio_description_errors) ? Math.max(0, Math.round(capture.audio_description_errors)) : 0;
    const descriptionSkipped = Number.isFinite(capture.audio_description_skipped) ? Math.max(0, Math.round(capture.audio_description_skipped)) : 0;
    const descriptionP95 = Number.isFinite(capture.audio_description_latency_ms_p95)
      ? `p95 ${Math.round(capture.audio_description_latency_ms_p95)} ms`
      : '';
    const descriptionAge = Number.isFinite(capture.audio_description_last_age_ms)
      ? Math.max(0, Math.round(capture.audio_description_last_age_ms))
      : null;
    const descriptionFresh = capture.audio_description_last_fresh === true && descriptionAge !== null;
    const provider = capture.audio_description_provider === 'qwen3-omni'
      ? 'Qwen3-Omni'
      : String(capture.audio_description_provider || 'Аудио');
    const kind = ({speech: 'речь', music: 'музыка', sound: 'звук', unknown: 'не распознано'})[capture.audio_description_last_kind] || 'неизвестный тип';
    const ageText = descriptionAge === null ? '' : `${Math.round(descriptionAge / 1000)} с назад`;
    const descriptionStatus = !capture.audio_description_configured
      ? 'описатель не подключён'
      : capture.loopback_paused
        ? 'анализ системного звука приостановлен'
        : !capture.loopback_running
          ? 'ожидает запуска захвата'
          : descriptionFresh
            ? `результат: ${kind} · ${ageText}`
            : descriptionAge !== null
              ? `нет свежего результата · последний ${ageText}`
              : descriptionCount > 0
                ? 'ожидает следующего аудиосегмента'
                : 'ожидает первого аудиосегмента';
    const stats = [`${descriptionCount} описаний`, descriptionP95, descriptionErrors ? `ошибок ${descriptionErrors}` : '', descriptionSkipped ? `пропущено ${descriptionSkipped}` : '']
      .filter(Boolean)
      .join(' · ');
    audioDescriptionElement.textContent = `${provider}: ${descriptionStatus} · ${stats}`;
    audioDescriptionElement.dataset.state = !capture.audio_description_configured || capture.loopback_paused || !capture.loopback_running
      ? 'off'
      : descriptionFresh
        ? 'ok'
        : descriptionErrors > 0 && descriptionCount === 0
          ? 'error'
          : 'warn';
  }
  if (!summary) return;
  const text = `Микрофон ${mic} · Экран ${screenLabel} · Системный звук ${loopback}`;
  if (summary.textContent !== text) summary.textContent = text;
  const freshnessAge = confirmedAge ?? captionAge;
  const visualStale = visualRunning && (age === null || !captionFresh || (freshnessAge !== null && freshnessAge > 6000));
  const loopbackStale = capture.loopback_running && (loopbackAge === null || loopbackAge > 3000 || loopbackSignalState !== 'signal_present');
  summary.dataset.state = capture.loopback_error || (visualRunning && visual.error_active)
    ? 'error'
    : (visualStale || loopbackStale ? 'warn' : 'ok');
  const compactScreen = !screenRunning
    ? 'выкл.'
    : visual.error_active
      ? 'ошибка'
      : age === null
      ? 'ждёт описания'
      : !captionFresh || (freshnessAge !== null && freshnessAge > 6000)
        ? `описание устарело ${Math.round((captionAge ?? age) / 1000)}с`
        : `описание ${Math.round((captionAge ?? age) / 1000)}с`;
  const compactLoopback = !capture.loopback_configured
    ? '\u043d\u0435\u0442 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438'
    : capture.loopback_paused
      ? '\u043f\u0430\u0443\u0437\u0430'
      : capture.loopback_running
        ? loopbackAge === null
          ? '\u0436\u0434\u0451\u0442 \u0434\u0430\u043d\u043d\u044b\u0445'
          : loopbackAge > 3000
            ? `\u043d\u0435\u0442 \u0441\u0432\u0435\u0436\u0438\u0445 \u0434\u0430\u043d\u043d\u044b\u0445 ${Math.round(loopbackAge / 1000)}\u0441`
            : loopbackSignalState === 'digital_silence'
              ? '\u0431\u0435\u0437 \u0441\u0438\u0433\u043d\u0430\u043b\u0430'
              : loopbackSignalState === 'nonzero_pcm_unclassified'
                ? 'PCM \u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d'
                : '\u0443\u0440\u043e\u0432\u0435\u043d\u044c \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d'
        : capture.loopback_error
          ? '\u043e\u0448\u0438\u0431\u043a\u0430'
          : capture.loopback_enabled
            ? '\u043e\u0436\u0438\u0434\u0430\u0435\u0442'
            : '\u0432\u044b\u043a\u043b.';
  const compactSummary = document.querySelector('#sensory-health-compact');
  if (compactSummary) {
    const compactMic = state.micActive || micOwner ? 'вкл.' : 'выкл.';
    const compactMusic = capture.soundscape_last_fresh === true
      && capture.soundscape_last_kind === 'music'
      && Number.isFinite(capture.soundscape_last_age_ms)
      && capture.soundscape_last_age_ms <= 20000
      ? ` · Музыка ${Math.round(Math.max(0, capture.soundscape_last_age_ms) / 1000)}с`
      : '';
    compactSummary.textContent = `Микр. ${compactMic}${compactMusic} · Экран ${compactScreen} · Звук ${compactLoopback}${attention.dnd ? ' · DND' : ''}`;
    compactSummary.dataset.state = summary.dataset.state;
    const musicTitle = compactMusic
      ? `Музыка обнаружена ${Math.round(Math.max(0, capture.soundscape_last_age_ms) / 1000)} с назад${Array.isArray(capture.soundscape_last_tags) && capture.soundscape_last_tags.length ? `; повторяющийся тег: ${capture.soundscape_last_tags.slice(0, 2).join(', ')}` : ''}`
      : capture.loopback_paused
        ? 'Анализ музыки приостановлен'
        : capture.soundscape_configured
          ? 'Нет свежего подтверждения музыки'
          : 'Анализ музыки не подключён';
    summary.title = `${text}. Инициатива: ${initiative}. ${musicTitle}.`;
    compactSummary.title = summary.title;
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
    document.querySelectorAll('nav.rail button').forEach(b => {
      if (b === button) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    const tab = button.dataset.tab;
    document.body.classList.toggle('settings-mode', tab === 'settings');
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
  window.__jawlScene?.setMotionState?.(on ? 'thinking' : 'idle');
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
    let audioIndex = 0;
    let audioChain = Promise.resolve();
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
          else if (event.type === 'audio' && event.index === audioIndex) {
            audioIndex += 1;
            earlySpeech.streamPending = true;
            syncSelfTtsSuppression();
            audioChain = audioChain.then(() => playEarlyAudioEvent(event)).catch(() => {});
          }
        } catch { /* partial line */ }
      }
    }
    await audioChain.catch(() => {});
    if (final) handleEnvelope(final, {speak: earlySpeech.scheduled === 0});
    else addMessage('system', 'Ход завершился без ответа.');
  } catch (error) {
    addMessage('system', 'Ошибка связи: ' + error.message);
  } finally {
    earlySpeech.streamPending = false;
    syncSelfTtsSuppression();
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
let selfTtsSuppressionActive = false;
let selfTtsSuppressionTimer = null;
let selfTtsSuppressionQueue = Promise.resolve();

function postSelfTtsSuppression(active) {
  selfTtsSuppressionQueue = selfTtsSuppressionQueue.catch(() => {}).then(() => fetch('/api/ambient-audio/playback', {
    method: 'POST',
    credentials: 'include',
    headers: API.headers(),
    body: JSON.stringify({active: Boolean(active), ttl_seconds: 30}),
    keepalive: true,
  })).catch(() => {});
}

function setSelfTtsSuppression(active) {
  const next = Boolean(active);
  if (next === selfTtsSuppressionActive) return;
  selfTtsSuppressionActive = next;
  postSelfTtsSuppression(next);
  if (selfTtsSuppressionTimer !== null) clearInterval(selfTtsSuppressionTimer);
  selfTtsSuppressionTimer = next
    ? setInterval(() => postSelfTtsSuppression(true), 10000)
    : null;
}

function syncSelfTtsSuppression() {
  const active = Boolean(
    earlySpeech?.streamPending
      || earlySpeech?.sources.size
      || state.speechPlayback?.markerLease,
  );
  setSelfTtsSuppression(active);
}

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
  playback.markerLease = false;
  syncSelfTtsSuppression();
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

function cancelSpeechPlayback(muted = false) {
  state.speechGeneration += 1;
  stopEarlySpeech(muted);
  releaseSpeechPlayback(state.speechPlayback, 'cancel');
}

// Speech-first: the server may push sentence WAVs before the turn ends.
// They are played immediately, and the full-text TTS call after `final` is
// skipped so the reply is never spoken twice.
const earlySpeech = {ctx: null, sources: new Set(), nextAt: 0, scheduled: 0, streamPending: false, muted: false};

function assistantSpeechActive() {
  return Boolean(state.speechPlayback) || earlySpeech.sources.size > 0;
}

function stopEarlySpeech(mute = false) {
  for (const source of earlySpeech.sources) {
    source.onended = null;
    try { source.stop(); } catch {}
    try { source.disconnect(); } catch {}
  }
  earlySpeech.sources.clear();
  earlySpeech.nextAt = 0;
  earlySpeech.scheduled = 0;
  earlySpeech.streamPending = false;
  earlySpeech.muted = mute;
  syncSelfTtsSuppression();
}

async function playEarlyAudioEvent(event) {
  if (earlySpeech.muted) return;
  if (!event || event.media_type !== 'audio/wav' || typeof event.data_base64 !== 'string') return;
  const binary = atob(event.data_base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  if (!earlySpeech.ctx) earlySpeech.ctx = new AudioContext();
  if (earlySpeech.ctx.state === 'suspended') await earlySpeech.ctx.resume();
  const buffer = await earlySpeech.ctx.decodeAudioData(bytes.buffer);
  if (!Number.isFinite(buffer?.duration) || buffer.duration <= 0 || buffer.duration > 30) return;
  const source = earlySpeech.ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(earlySpeech.ctx.destination);
  const startAt = Math.max(earlySpeech.ctx.currentTime + 0.05, earlySpeech.nextAt);
  source.start(startAt);
  earlySpeech.nextAt = startAt + buffer.duration;
  earlySpeech.scheduled += 1;
  earlySpeech.sources.add(source);
  syncSelfTtsSuppression();
  source.onended = () => {
    earlySpeech.sources.delete(source);
    syncSelfTtsSuppression();
  };
  setSpeechStopEnabled(true);
}

function setSpeechStopEnabled(enabled) {
  const button = document.querySelector('#speech-stop');
  if (button) button.disabled = !enabled;
  const hudStop = document.querySelector('#hud-stop');
  if (hudStop) hudStop.disabled = !enabled;
}

document.querySelector('#speech-stop')?.addEventListener('click', () => cancelSpeechPlayback(true));
document.querySelector('#hud-stop')?.addEventListener('click', () => cancelSpeechPlayback(true));
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
        playback.markerLease = true;
        syncSelfTtsSuppression();
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
    if (isCurrent()) {
      state.speechErrorNoticeKey = null;
      releaseSpeechPlayback(playback, 'done');
    }
  } catch (error) {
    if (state.speechPlayback === playback && generation === state.speechGeneration) {
      const cancelled = playback.abortController.signal.aborted || error?.code === 'TTS_CANCELLED';
      if (!cancelled) {
        const status = Number.isInteger(error?.status) ? ` Код: ${error.status}.` : '';
        const guidance = error?.status === 503
          ? 'TTS недоступен. Проверьте службу речи и повторите попытку.'
          : 'Попробуйте отправить ответ ещё раз.';
        const noticeKey = `${error?.status ?? error?.code ?? 'network'}:${guidance}`;
        if (state.speechErrorNoticeKey !== noticeKey) {
          state.speechErrorNoticeKey = noticeKey;
          addMessage('system', `Не удалось воспроизвести голосовой ответ. ${guidance}${status}`);
        }
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
function selectDefaultFifineDevice(inputs) {
  const saved = localStorage.getItem('jawl.app.micDeviceId');
  if (saved !== null) return saved;
  const fifine = (inputs || []).find(d =>
    d && d.deviceId && d.deviceId !== 'default' && d.deviceId !== 'communications' &&
    String(d.label || '').toLowerCase().includes('fifine'));
  if (fifine) {
    setPreferredMicId(fifine.deviceId);
    return fifine.deviceId;
  }
  return '';
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
    const wanted = preferredMicId() || selectDefaultFifineDevice(inputs);
    if (wanted && inputs.some(d => d.deviceId === wanted)) micSelect.value = wanted;
  } catch { /* enumeration optional */ }
}

micSelect?.addEventListener('change', () => setPreferredMicId(micSelect.value));
navigator.mediaDevices?.addEventListener?.('devicechange', refreshMicDevices);

async function startMic() {
  if (micStarting || state.micActive) return;
  micStarting = true;
  setMicButtonState(Boolean(state.micActive), true);
  announceMicStatus('Запускаю микрофон.');
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
      pendingUploadFrames: [], pendingUploadSamples: 0,
      turnGeneration: 0, active: true, abortController: new AbortController(), flushWaiters: [],
      overlapPlayback: null, overlapStarted: false, overlapEarlySpeech: false,
      voicedMs: 0, bargeInConfirmed: false,
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
          body: JSON.stringify({
            ...payload,
            assistant_speaking: Boolean(micCapture.overlapStarted && !micCapture.bargeInConfirmed),
          }), signal,
        });
        micHelpers.requireVoiceResponseOk(response, 'voice/draft');
        return response.json();
      },
      onDecision: (response) => {
        if (state.mic !== micCapture || !micCapture.active) return;
        const required = Number(response?.required_ms);
        if (Number.isFinite(required) && required > 0) {
          micCapture.serverDecision = {
            required_ms: required,
            action: String(response?.duplex_action || ''),
          };
        }
        const gesture = String(response?.avatar_gesture || '');
        if (gesture && gesture !== micCapture.lastGesture && !micCapture.bargeInConfirmed) {
          micCapture.lastGesture = gesture;
          window.__jawlScene?.triggerMotion?.(gesture);
        }
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
          mic.draftText = '';
          mic.overlapPlayback = state.speechPlayback;
          mic.overlapStarted = assistantSpeechActive();
          mic.overlapEarlySpeech = !state.speechPlayback && mic.overlapStarted;
          mic.voicedMs = 0;
          mic.bargeInConfirmed = false;
          mic.serverDecision = null;
          mic.lastGesture = '';
          mic.turnGeneration += 1;
          mic.drafts.reset();
          mic.drafts.resume();
        }
        mic.heard = true;
        if (!state.speechPlayback) window.__jawlScene?.setMotionState?.('listening');
        micState.textContent = mic.draftText ? 'Слышу (предварительно): ' + mic.draftText.slice(0, 160) : 'Слушаю…';
      }
      if (mic.heard && result.voiceActive && result.rms >= mic.inputGate.config.closeRms) {
        mic.voicedMs += event.data.byteLength / Float32Array.BYTES_PER_ELEMENT * 1000 / context.sampleRate;
      }
      updateMicTurn(mic);
      for (const frame of result.frames) {
        mic.pendingUploadFrames.push(frame);
        mic.pendingUploadSamples += frame.length;
      }
      if (mic.pendingUploadSamples >= Math.round(context.sampleRate * 60)) {
        const error = new Error('очередь распознавания не успевает обработать минутный буфер речи');
        voiceCaptureDiagnostic(mic, 'upload_buffer_exhausted', error);
        addMessage('system', 'Распознавание отстаёт более чем на минуту. Остановил захват, чтобы не потерять конец реплики.');
        void stopMic();
        return;
      }
      // The worklet emits ~43 ms blocks at 48 kHz. Uploading each block as a
      // separate HTTP request can outrun the local ASR/VoiceMem endpoint and
      // used to shut the microphone off at six queued requests. Batch speech
      // into ~250 ms requests while preserving the same PCM stream.
      if (mic.pendingUploadSamples >= Math.round(context.sampleRate * 0.25)) {
        flushPendingMicAudio(mic, context.sampleRate);
      }
    };

    state.mic.poll = setInterval(() => {
      const mic = state.mic;
      if (!mic || !mic.active || !mic.heard || mic.finalizing) return;
      const decision = updateMicTurn(mic);
      if (decision.action === 'commit_turn' || decision.action === 'finish_backchannel') {
        void finishUtterance();
      }
    }, 100);

    state.micActive = true;
    setMicButtonState(true);
    announceMicStatus('Микрофон включён.');
    chatMic.style.background = 'var(--accent)';
    if (typeof document !== 'undefined') {
      const hudMic = document.querySelector('#hud-mic');
      if (hudMic) hudMic.style.background = 'var(--accent)';
    }
    micState.textContent = 'Микрофон включён — говорите.';
    setVal('mic-state', 'Микрофон включён.');
  } catch (error) {
    stream?.getTracks().forEach(t => t.stop());
    if (context && context.state !== 'closed') await context.close().catch(() => {});
    await captureLease?.release();
    if (pendingCaptureLease === captureLease) pendingCaptureLease = null;
    if (startGeneration === micStartGeneration) {
      setMicButtonState(false);
      announceMicStatus('Микрофон недоступен. ' + error.message);
      micState.textContent = 'Микрофон недоступен: ' + error.message;
    }
  } finally {
    if (startGeneration === micStartGeneration) {
      micStarting = false;
      setMicButtonState(Boolean(state.micActive));
    }
  }
}

function updateMicTurn(mic) {
  if (!mic.heard || mic.finalizing) return {action: 'hold_turn'};
  const decision = mic.helpers.decideMicTurn({
    text: mic.draftText, overlap: mic.overlapStarted && !mic.bargeInConfirmed,
    voicedMs: mic.voicedMs, silenceMs: performance.now() - mic.inputGate.lastVoiceAt,
    normalSilenceMs: mic.serverDecision?.required_ms ?? mic.inputGate.config.silenceMs,
  });
  if (decision.action === 'cancel_tts' && !mic.bargeInConfirmed) {
    mic.bargeInConfirmed = true;
    // A late draft from this utterance must not cancel a newer playback owner.
    if (state.speechPlayback && state.speechPlayback === mic.overlapPlayback) cancelSpeechPlayback(true);
    else if (mic.overlapEarlySpeech) stopEarlySpeech(true);
    mic.overlapEarlySpeech = false;
  }
  return decision;
}

function getCaptureClientId() {
  return globalThis.crypto?.randomUUID?.() || `desktop-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function uploadChunk(samples, sampleRate) {
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
  if (!task) {
    // Preserve the captured PCM and let the queue drain before sending more.
    mic.pendingUploadFrames.unshift(samples);
    mic.pendingUploadSamples += samples.length;
    return null;
  }
  else task.catch(fail);
  return task;
}

function flushPendingMicAudio(mic, sampleRate) {
  if (!mic || !mic.active || !mic.pendingUploadFrames?.length) return null;
  if (mic.uploadQueue.pending >= 6) {
    mic.backpressureActive = true;
    micState.textContent = 'Поток распознавания отстаёт — звук временно буферизуется.';
    return null;
  }
  const targetSamples = Math.max(1, Math.round(sampleRate * 2));
  const frames = [];
  let totalSamples = 0;
  while (mic.pendingUploadFrames.length && totalSamples < targetSamples) {
    const frame = mic.pendingUploadFrames.shift();
    frames.push(frame);
    totalSamples += frame.length;
  }
  const samples = new Float32Array(totalSamples);
  let offset = 0;
  for (const frame of frames) {
    samples.set(frame, offset);
    offset += frame.length;
  }
  mic.pendingUploadSamples = Math.max(0, mic.pendingUploadSamples - totalSamples);
  if (mic.uploadQueue.pending >= 5) mic.backpressureActive = true;
  const task = uploadChunk(samples, sampleRate);
  if (!task) {
    mic.pendingUploadFrames.unshift(...frames);
    mic.pendingUploadSamples += totalSamples;
  }
  return task;
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
    if (bounded) {
      queue.pending = Math.max(0, queue.pending - 1);
      if (queue.pending < 5 && mic.backpressureActive) {
        mic.backpressureActive = false;
        if (mic.active && mic.heard && !mic.finalizing) micState.textContent = 'Микрофон включён — говорите.';
      }
      if (mic.active && !mic.finalizing && mic.pendingUploadSamples >= Math.round((mic.context?.sampleRate || 48000) * 0.25)) {
        flushPendingMicAudio(mic, mic.context?.sampleRate || 48000);
      }
    }
  });
  return task;
}

async function drainPendingMicAudio(mic, sampleRate) {
  // Keep the old utterance identity until all captured PCM is accepted by ASR.
  while (mic.active && (mic.pendingUploadFrames.length || mic.uploadQueue.pending)) {
    if (mic.pendingUploadFrames.length && mic.uploadQueue.pending < 6) {
      flushPendingMicAudio(mic, sampleRate);
    }
    const pending = mic.uploadQueue.tail;
    await pending.catch(() => {});
    if (pending === mic.uploadQueue.tail && mic.uploadQueue.pending === 0 && !mic.pendingUploadFrames.length) break;
  }
}

function finalizeAfterMicUploads(mic, finalize) {
  const previousUploads = mic.uploadQueue.tail;
  mic.uploadQueue = {tail: Promise.resolve(), pending: 0};
  return previousUploads.catch(() => {}).then(() => mic.active ? finalize() : null);
}

function micTurnIsCurrent(mic, generation) {
  return Boolean(mic.active && state.mic === mic && mic.turnGeneration === generation);
}

function micCaptureIsCurrent(mic) {
  return Boolean(mic.active && state.mic === mic);
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
  const suppressBackchannel = mic.overlapStarted && !mic.bargeInConfirmed;
  micState.textContent = 'Распознаю…';
  try {
    await flushMicWorklet(mic);
    if (!micTurnIsCurrent(mic, turnGeneration)) return;
    await drainPendingMicAudio(mic, mic.context.sampleRate);
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
        suppress_backchannel: suppressBackchannel,
      }),
      signal: mic.abortController.signal,
      });
      mic.helpers.requireVoiceResponseOk(response, 'voice/end');
      return response.json();
    });
    if (!data || !micCaptureIsCurrent(mic)) return;
    if (data.filtered === 'user_backchannel') window.__jawlScene?.triggerMotion?.('nod');
    if (data.transcript) addMessage('user', data.transcript);
    const answers = data.responses || [];
    const last = answers[answers.length - 1];
    if (last) handleEnvelope(last, {speak: !mic.heard});
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
  setMicButtonState(false);
  announceMicStatus('Микрофон выключен.');
  cancelSpeechPlayback();
  chatMic.style.background = '';
  if (typeof document !== 'undefined') {
    const hudMic = document.querySelector('#hud-mic');
    if (hudMic) hudMic.style.background = '';
  }
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
    const status = document.querySelector('#wardrobe-status');
    if (status) status.textContent = '';
    for (const model of (w.models || [])) {
      const modelName = String(model.model || 'Без названия');
      const isWorn = window.__jawlScene?.wornModel === modelName;
      const tile = document.createElement('button');
      tile.type = 'button';
      tile.className = 'model-tile' + (isWorn ? ' worn' : '');
      tile.setAttribute('aria-pressed', String(isWorn));
      const icon = document.createElement('span');
      icon.className = 'em';
      icon.setAttribute('aria-hidden', 'true');
      icon.innerHTML = '<svg class="ui-icon" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"></circle><path d="M4 21a8 8 0 0 1 16 0"></path></svg>';
      const name = document.createElement('span');
      name.className = 'nm';
      name.textContent = modelName;
      const size = document.createElement('span');
      size.className = 'sz';
      size.textContent = `${(Number(model.size_bytes) / 1048576).toFixed(1)} МБ`;
      tile.setAttribute('aria-label', `${modelName} ${size.textContent} — надеть модель`);
      tile.append(icon, name, document.createTextNode(' '), size);
      tile.addEventListener('click', async () => {
        tile.disabled = true;
        tile.setAttribute('aria-busy', 'true');
        if (status) status.textContent = `Надеваем модель ${modelName}.`;
        try {
          const worn = await window.__jawlScene?.wear(modelName);
          if (!worn) {
            tile.disabled = false;
            tile.classList.add('error');
            tile.setAttribute('aria-busy', 'false');
            if (status) status.textContent = `Не удалось надеть модель ${modelName}. Можно повторить.`;
            return;
          }
          await loadWardrobe();
        } catch (error) {
          tile.disabled = false;
          tile.classList.add('error');
          tile.setAttribute('aria-busy', 'false');
          if (status) status.textContent = `Не удалось надеть модель ${modelName}: ${String(error?.message || error)}.`;
        }
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
      const response = await fetch('/api/logs/agent?tail=40', {credentials: 'include', headers: API.headers()});
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw new Error(payload.error || 'Log request failed');
      el.textContent = (payload.lines || []).join('\n') || 'Журнал пока пуст';
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
// Chameleon window modes: Compact HUD <-> Studio Drawer & OBS (?mode=obs)
// ---------------------------------------------------------------------------

let alwaysOnTop = false;
let clickThrough = false;
let dndActive = false;
let sensesActive = false;

function syncHudToggles() {
  if (typeof document === 'undefined') return;
  const dndBtn = document.querySelector('#hud-dnd');
  if (dndBtn) {
    dndBtn.style.background = dndActive ? 'rgba(224,112,95,.32)' : '';
    dndBtn.setAttribute('aria-pressed', String(dndActive));
  }
  const sensesBtn = document.querySelector('#hud-senses');
  if (sensesBtn) {
    sensesBtn.style.background = sensesActive ? 'var(--accent-2)' : '';
    sensesBtn.setAttribute('aria-pressed', String(sensesActive));
  }
  const ghostBtn = document.querySelector('#hud-ghost');
  if (ghostBtn) {
    ghostBtn.style.background = clickThrough ? 'var(--accent-2)' : '';
    ghostBtn.setAttribute('aria-pressed', String(clickThrough));
  }
}

async function toggleDndMode() {
  const next = !dndActive;
  try {
    const r = await fetch('/api/attention', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify({dnd: next}),
    });
    if (r.ok) {
      dndActive = next;
      setVal('proactive-state', dndActive ? 'Не беспокоить (DND)' : 'включён');
      syncHudToggles();
    }
  } catch {}
}

async function toggleSensesMode() {
  const next = !sensesActive;
  try {
    const r = await fetch('/api/ambient-memory/config', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      body: JSON.stringify({mode: 'set', enabled: next}),
    });
    if (r.ok) {
      sensesActive = next;
      setVal('ambient-state', sensesActive ? 'активна' : 'пауза');
      syncHudToggles();
    }
  } catch {}
}

function syncDesktopWindowMode() {
  const compact = Boolean(document.body?.classList?.contains('compact-mode'));
  const pinBtn = document.querySelector('#hud-pin');
  if (pinBtn) {
    pinBtn.style.background = alwaysOnTop ? 'var(--accent-2)' : '';
    pinBtn.setAttribute('aria-pressed', String(alwaysOnTop));
  }
  syncHudToggles();
  try {
    window.__jawlDesktop?.setWindowMode?.({compact, alwaysOnTop, clickThrough});
  } catch {}
}

function setCompactMode(compact, {defaultPin = true} = {}) {
  const next = Boolean(compact);
  if (!next) clickThrough = false;
  if (next && defaultPin && localStorage.getItem('jawl.app.alwaysOnTop') === null) {
    alwaysOnTop = true;
  }
  document.body?.classList?.toggle('compact-mode', next);
  try { localStorage.setItem('jawl.app.compactMode', next ? '1' : '0'); } catch {}
  syncDesktopWindowMode();
  setTimeout(() => window.dispatchEvent?.(new Event('resize')), 30);
  // Also persist to electron userData via IPC (already done in syncDesktopWindowMode)
}

// Restore compact mode from localStorage on boot
try {
  const savedCompact = localStorage.getItem('jawl.app.compactMode');
  if (savedCompact === '1') {
    document.body?.classList?.add('compact-mode');
    alwaysOnTop = localStorage.getItem('jawl.app.alwaysOnTop') === '1' || localStorage.getItem('jawl.app.alwaysOnTop') === null;
    syncDesktopWindowMode();
    // Also notify Electron to resize window
    setTimeout(() => {
      syncDesktopWindowMode();
    }, 100);
  }
} catch (_) {}

function toggleAlwaysOnTop() {
  alwaysOnTop = !alwaysOnTop;
  try { localStorage.setItem('jawl.app.alwaysOnTop', alwaysOnTop ? '1' : '0'); } catch {}
  syncDesktopWindowMode();
}

function toggleClickThrough() {
  clickThrough = !clickThrough;
  syncDesktopWindowMode();
}

function toggleCompactMode() {
  setCompactMode(!document.body?.classList?.contains('compact-mode'));
}

document.querySelector('#toggle-compact')?.addEventListener('click', () => setCompactMode(true));
document.querySelector('#hud-expand')?.addEventListener('click', () => setCompactMode(false));
document.querySelector('#hud-pin')?.addEventListener('click', toggleAlwaysOnTop);
document.querySelector('#hud-ghost')?.addEventListener('click', toggleClickThrough);
document.querySelector('#hud-dnd')?.addEventListener('click', () => void toggleDndMode());
document.querySelector('#hud-senses')?.addEventListener('click', () => void toggleSensesMode());
document.querySelector('#hud-mic')?.addEventListener('click', () => {
  if (micStarting || state.micActive) void stopMic();
  else void startMic();
});

try {
  alwaysOnTop = localStorage.getItem('jawl.app.alwaysOnTop') === '1';
  const params = new URLSearchParams(globalThis.location?.search || '');
  const modeParam = params.get('mode');
  if (modeParam === 'obs') {
    document.body?.classList?.add('obs-mode');
  } else if (modeParam === 'compact' || localStorage.getItem('jawl.app.compactMode') === '1') {
    setCompactMode(true, {defaultPin: false});
  } else if (alwaysOnTop) {
    syncDesktopWindowMode();
  }
  window.addEventListener?.('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && e.code === 'KeyM') {
      e.preventDefault();
      toggleCompactMode();
    } else if (e.ctrlKey && e.shiftKey && e.code === 'KeyG') {
      e.preventDefault();
      toggleClickThrough();
    }
  });
  // When hovering the HUD dock while clickThrough is on, temporarily allow mouse clicks on the dock!
  const hudDock = document.querySelector('.hud-dock');
  hudDock?.addEventListener('mouseenter', () => {
    if (clickThrough) {
      window.__jawlDesktop?.setWindowMode?.({
        compact: Boolean(document.body?.classList?.contains('compact-mode')),
        alwaysOnTop,
        clickThrough: false,
      });
    }
  });
  hudDock?.addEventListener('mouseleave', () => {
    if (clickThrough) {
      window.__jawlDesktop?.setWindowMode?.({
        compact: Boolean(document.body?.classList?.contains('compact-mode')),
        alwaysOnTop,
        clickThrough: true,
      });
    }
  });
} catch { /* non-browser test harness safe */ }

// ---------------------------------------------------------------------------
// go
// ---------------------------------------------------------------------------

boot();
startRefresh();
loadWardrobe();
refreshMicDevices();
if (typeof loadSettings === 'function') loadSettings();
