// Settings section: config-hub rendered as typed V.E.G.A.-style fields
// (toggles, sliders, selects with human labels) — not a text editor.
// Field descriptors know each key's type and Russian label; unknown keys
// fall back to a sensible input by value type.

const SETTING_FIELDS = [
  // --- interfaces: mcp ---
  { key: 'interfaces:mcp.enabled', label: 'MCP-интерфейс', desc: 'Канал внешних MCP-серверов', type: 'bool' },
  { key: 'interfaces:mcp.startup_timeout_sec', label: 'MCP: таймаут старта', type: 'number', min: 1, max: 300, step: 1, unit: 'сек' },
  { key: 'interfaces:mcp.request_timeout_sec', label: 'MCP: таймаут запроса', type: 'number', min: 1, max: 600, step: 1, unit: 'сек' },
  { key: 'interfaces:mcp.max_catalog_items', label: 'MCP: макс. инструментов', type: 'number', min: 0, max: 500, step: 1, unit: 'шт' },
  { key: 'interfaces:mcp.max_result_chars', label: 'MCP: макс. символов', type: 'number', min: 0, max: 100000, step: 1000, unit: 'симв' },
  { key: 'interfaces:mcp.max_binary_bytes', label: 'MCP: макс. бинарных', type: 'number', min: 0, max: 104857600, step: 1048576, unit: 'МБ·м' },
  // --- interfaces: debug broker ---
  { key: 'interfaces:debug_broker.enabled', label: 'Debug Broker', desc: 'RE/отладочный контур', type: 'bool' },
  { key: 'interfaces:debug_broker.auto_start', label: 'Debug Broker: автозапуск', type: 'bool' },
  { key: 'interfaces:debug_broker.startup_timeout_sec', label: 'Debug Broker: старт', type: 'number', min: 1, max: 300, unit: 'сек' },
  { key: 'interfaces:debug_broker.request_timeout_sec', label: 'Debug Broker: запрос', type: 'number', min: 1, max: 600, unit: 'сек' },
  { key: 'interfaces:debug_broker.max_result_chars', label: 'Debug Broker: макс. симв.', type: 'number', min: 0, max: 100000, step: 1000, unit: 'симв' },
  { key: 'interfaces:debug_broker.max_sessions', label: 'Debug Broker: сессий', type: 'number', min: 1, max: 32, unit: 'шт' },
  { key: 'interfaces:debug_broker.re_root', label: 'Debug Broker: корень RE', type: 'text' },
  // --- interfaces: multimodality ---
  { key: 'interfaces:multimodality.enabled', label: 'Мультимодальность', desc: 'Изображения и медиа в ходы', type: 'bool' },
  { key: 'interfaces:multimodality.video_understanding_enabled', label: 'Понимание видео', type: 'bool' },
  { key: 'interfaces:multimodality.media_generation_enabled', label: 'Генерация медиа', type: 'bool' },
  { key: 'interfaces:multimodality.media_request_timeout_sec', label: 'Медиа: таймаут', type: 'number', min: 1, max: 600, unit: 'сек' },
  { key: 'interfaces:multimodality.media_poll_interval_sec', label: 'Медиа: опрос', type: 'number', min: 0.5, max: 60, step: 0.5, unit: 'сек' },
  { key: 'interfaces:multimodality.media_max_upload_mb', label: 'Медиа: загрузка макс.', type: 'number', min: 1, max: 200, unit: 'МБ' },
  { key: 'interfaces:multimodality.media_max_download_mb', label: 'Медиа: скачивание макс.', type: 'number', min: 1, max: 500, unit: 'МБ' },
  // --- llm (через config-hub секции) ---
  { key: 'settings:llm.temperature', label: 'Температура', desc: '0.1 — исполнительность, 1.0 — обычный', type: 'range', min: 0, max: 2, step: 0.01 },
  { key: 'settings:llm.max_react_steps', label: 'Максимум шагов ReAct', desc: 'После лимита такт закрывается', type: 'number', min: 1, max: 100, unit: 'шаг' },
  { key: 'settings:llm.language', label: 'Язык мышления и ответов', type: 'enum', options: [['ru', 'ru — русский'], ['en', 'en — английский'], ['auto', 'auto — по собеседнику']] },
  { key: 'settings:identity.agent_name', label: 'Имя агента', desc: 'В системный промпт и приветствие', type: 'text' },
  { key: 'settings:system.proactive_guidance', label: 'Проактивные подсказки', desc: 'Агент сам предлагает следующий шаг', type: 'bool' },
  { key: 'settings:llm.is_multimodal', label: 'Мультимодальность модели', desc: 'Изображения и скриншоты в модель', type: 'bool' },
  // --- llm выход ---
  { key: 'settings:llm.max_output_tokens', label: 'Максимум выходных токенов', desc: 'Лимит «размышлений» за шаг', type: 'number', min: 64, max: 32768, step: 64, unit: 'ток' },
  { key: 'settings:llm.context_tokens', label: 'Контекст модели', desc: '64k рекомендован для ReAct', type: 'number', min: 1024, max: 131072, step: 1024, unit: 'ток' },
];

const SETTING_GROUPS = [
  { title: 'Интерфейсы · MCP', match: (k) => k.startsWith('interfaces:mcp') },
  { title: 'Интерфейсы · Debug Broker', match: (k) => k.startsWith('interfaces:debug_broker') },
  { title: 'Мультимодальность', match: (k) => k.startsWith('interfaces:multimodality') },
  { title: 'Личность и LLM', match: (k) => k.startsWith('settings:llm') || k.startsWith('settings:identity') || k.startsWith('settings:system') },
];

function fieldDescriptor(key, value) {
  const known = SETTING_FIELDS.find(f => f.key === key);
  if (known) return known;
  // auto by value type
  if (typeof value === 'boolean') return { key, label: key.split(':').pop(), type: 'bool' };
  if (typeof value === 'number') return { key, label: key.split(':').pop(), type: 'number' };
  return { key, label: key.split(':').pop(), type: 'text' };
}

let configHub = null;
const settingsDirty = new Map();
let settingsSaving = false;

function updateSaveButton() {
  const save = document.querySelector('#settings-save');
  if (!save) return;
  save.textContent = settingsSaving
    ? 'сохранение…'
    : `сохранить (${settingsDirty.size})`;
  save.disabled = settingsSaving || settingsDirty.size === 0;
}

function markSettingDirty(key, value) {
  settingsDirty.set(key, value);
  updateSaveButton();
}

async function loadSettings() {
  const list = document.querySelector('#settings-list');
  if (!list) return;
  try {
    const r = await fetch('/api/config-hub', {credentials: 'include', headers: API.headers()});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const hub = await r.json();
    if (!hub || (!hub.ok && !hub.values)) throw new Error('config hub недоступен');
    configHub = hub;
    renderSettings('');
  } catch (e) {
    if (settingsDirty.size) {
      setStatusLine(`не удалось обновить настройки; черновики сохранены: ${e.message}`);
      renderSettings(document.querySelector('#settings-search')?.value || '');
    } else {
      list.textContent = 'config hub недоступен';
    }
  }
}

function flattenHub(values, prefix = '') {
  const out = [];
  for (const [key, value] of Object.entries(values || {})) {
    const path = prefix ? `${prefix}:${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      out.push(...flattenHub(value, path));
    } else {
      out.push([path, value]);
    }
  }
  return out;
}

function renderSettings(filter) {
  const list = document.querySelector('#settings-list');
  if (!list || !configHub) return;
  // config-hub returns FLAT dotted keys ('settings:llm.temperature') —
  // flattenHub is only for nested payloads; use whichever shape arrived.
  const values = configHub.values || configHub.sections || {};
  const isFlat = Object.keys(values).some(k => k.includes(':'));
  const flat = isFlat ? Object.entries(values) : flattenHub(values);
  const entries = flat.filter(([key]) =>
    !filter || key.toLowerCase().includes(filter.toLowerCase()));
  list.replaceChildren();
  if (!entries.length) list.textContent = 'ничего не найдено';

  // group by descriptor
  const groups = SETTING_GROUPS.map(g => ({...g, entries: []}));
  const other = { title: 'Прочее', entries: [] };
  for (const entry of entries) {
    const group = groups.find(g => g.match(entry[0])) || other;
    group.entries.push(entry);
  }

  for (const group of [...groups, other]) {
    if (!group.entries.length) continue;
    const card = document.createElement('div');
    card.className = 'card';
    const h = document.createElement('h3');
    h.textContent = group.title;
    card.appendChild(h);
    for (const [key, value] of group.entries) {
      card.appendChild(renderField(key, settingsDirty.has(key) ? settingsDirty.get(key) : value));
    }
    list.appendChild(card);
  }
  // save button
  const save = document.createElement('button');
  save.id = 'settings-save';
  save.className = 'btn';
  save.type = 'button';
  save.addEventListener('click', saveSettings);
  list.appendChild(save);
  updateSaveButton();
}

function renderField(key, value) {
  const d = fieldDescriptor(key, value);
  const row = document.createElement('div');
  row.className = 'field';
  // label block
  const fl = document.createElement('div');
  fl.className = 'fl';
  const fn = document.createElement('div');
  fn.className = 'fn';
  fn.textContent = d.label;
  fl.appendChild(fn);
  if (d.desc) {
    const fd = document.createElement('div');
    fd.className = 'fd';
    fd.textContent = d.desc;
    fl.appendChild(fd);
  }
  row.appendChild(fl);

  let control;
  if (d.type === 'bool') {
    control = document.createElement('span');
    control.className = 'sw';
    control.setAttribute('role', 'switch');
    control.setAttribute('aria-checked', String(!!value));
    control.addEventListener('click', () => {
      const next = control.getAttribute('aria-checked') !== 'true';
      control.setAttribute('aria-checked', String(next));
      markSettingDirty(key, next);
    });
  } else if (d.type === 'range') {
    const wrap = document.createElement('span');
    wrap.className = 'fc';
    const range = document.createElement('input');
    range.type = 'range';
    range.min = d.min ?? 0; range.max = d.max ?? 100; range.step = d.step ?? 1;
    range.value = Number(value) || 0;
    const num = document.createElement('input');
    num.type = 'number';
    num.min = range.min; num.max = range.max; num.step = range.step;
    num.value = range.value;
    range.addEventListener('input', () => { num.value = range.value; markSettingDirty(key, Number(range.value)); });
    num.addEventListener('input', () => { range.value = num.value; markSettingDirty(key, Number(num.value)); });
    wrap.append(range, num);
    control = wrap;
  } else if (d.type === 'number') {
    const wrap = document.createElement('span');
    wrap.className = 'fc';
    const num = document.createElement('input');
    num.type = 'number';
    num.value = Number(value) || 0;
    if (d.min !== undefined) num.min = d.min;
    if (d.max !== undefined) num.max = d.max;
    if (d.step !== undefined) num.step = d.step;
    num.addEventListener('input', () => markSettingDirty(key, Number(num.value)));
    wrap.appendChild(num);
    if (d.unit) {
      const u = document.createElement('span');
      u.className = 'unit';
      u.textContent = d.unit;
      wrap.appendChild(u);
    }
    control = wrap;
  } else if (d.type === 'enum') {
    control = document.createElement('select');
    for (const [v, label] of (d.options || [])) {
      const option = document.createElement('option');
      option.value = v;
      option.textContent = label;
      control.appendChild(option);
    }
    control.value = String(value ?? '');
    control.addEventListener('change', () => markSettingDirty(key, control.value));
  } else {
    control = document.createElement('input');
    control.type = 'text';
    control.value = value === null || value === undefined ? '' : String(value);
    control.addEventListener('input', () => markSettingDirty(key, control.value));
  }
  row.appendChild(control);
  return row;
}

async function saveSettings() {
  if (!configHub || !settingsDirty.size || settingsSaving) return;
  const values = Object.fromEntries(settingsDirty);
  settingsSaving = true;
  updateSaveButton();
  try {
    const r = await fetch('/api/config-hub/save', {
      method: 'POST',
      credentials: 'include',
      headers: API.headers(),
      body: JSON.stringify({values, expected_revision: configHub.revision}),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    if (!d || d.ok !== true) throw new Error(d?.error || 'сервер не подтвердил сохранение');
    if (d.unknown?.length || d.missing?.length) {
      throw new Error(`не записаны ключи: ${[...(d.unknown || []), ...(d.missing || [])].join(', ')}`);
    }
    for (const [key, savedValue] of Object.entries(values)) {
      if (settingsDirty.get(key) === savedValue) settingsDirty.delete(key);
    }
    if (typeof d.revision === 'string') configHub.revision = d.revision;
    updateSaveButton();
    // JAWL reads settings.yaml at startup: apply means save + agent restart.
    // The hub itself reports restart_required; honor it automatically so the
    // UI never shows stale "not applied" values.
    if (d.restart_required) {
      setStatusLine('настройки сохранены — перезапускаю JAWL…');
      try {
        const restart = await fetch('/api/jawl/restart', {
          method: 'POST', credentials: 'include', headers: API.headers(), body: '{}'});
        if (!restart.ok) throw new Error(`HTTP ${restart.status}`);
        const result = await restart.json();
        if (!result || result.ok !== true) {
          throw new Error(result?.error || 'сервер не подтвердил перезапуск');
        }
        setStatusLine(`JAWL перезапускается с новыми настройками…${settingsDirty.size ? '; остались несохранённые черновики' : ''}`);
      } catch (e) {
        setStatusLine(`сохранено, но перезапуск не удался: ${e.message}${settingsDirty.size ? '; остались несохранённые черновики' : ''}`);
      }
    } else {
      setStatusLine(`настройки сохранены${settingsDirty.size ? '; остались несохранённые черновики' : ''}`);
    }
    await loadSettings();
  } catch (e) {
    setStatusLine('не сохранено; черновики сохранены: ' + e.message);
    alert('Ошибка сохранения: ' + e.message);
  } finally {
    settingsSaving = false;
    updateSaveButton();
  }
}

function setStatusLine(text) {
  const el = document.querySelector('#conn-status');
  if (el) el.textContent = text;
}

document.querySelector('#settings-search')?.addEventListener('input', (e) => {
  renderSettings(e.target.value);
});

// Shared microphone capture configuration. Values are saved through the
// capture lease endpoint and are read by the server on the next mic acquire.
const MIC_CAPTURE_FIELDS = {
  gate_open: '#mic-gate-open',
  gate_close: '#mic-gate-close',
  silence_ms: '#mic-silence-ms',
  pre_roll_ms: '#mic-pre-roll-ms',
};
let micCaptureRevision = null;
let micCaptureWritable = false;
let micCaptureLoading = false;
let micCaptureSaving = false;
let micCaptureDirty = false;
let micCaptureNeedsReload = false;

function micCaptureControls() {
  return Object.fromEntries(Object.entries(MIC_CAPTURE_FIELDS).map(([key, selector]) => [
    key, document.querySelector(selector),
  ]));
}

function micCaptureValues() {
  return Object.fromEntries(Object.entries(micCaptureControls()).map(([key, input]) => [
    key, input?.value.trim() ? Number(input.value) : Number.NaN,
  ]));
}

function setMicCaptureStatus(message) {
  const status = document.querySelector('#mic-capture-disabled');
  if (status) status.textContent = message;
}

function setMicCaptureError(message) {
  const error = document.querySelector('#mic-capture-error');
  if (!error) return;
  error.textContent = message;
  error.hidden = !message;
}

function updateMicCaptureControls() {
  const fieldset = document.querySelector('#mic-capture-fields');
  const save = document.querySelector('#mic-capture-save');
  const reload = document.querySelector('#mic-capture-reload');
  if (fieldset) fieldset.disabled = !micCaptureWritable || micCaptureLoading || micCaptureSaving;

  const values = micCaptureValues();
  const controls = micCaptureControls();
  const individuallyValid = Object.values(controls).every(input => input && input.checkValidity());
  const thresholdsValid = Number.isFinite(values.gate_open)
    && Number.isFinite(values.gate_close) && values.gate_close < values.gate_open;
  if (micCaptureDirty && !individuallyValid) {
    setMicCaptureError('Заполните все поля и проверьте допустимые диапазоны.');
  } else if (micCaptureDirty && !thresholdsValid) {
    setMicCaptureError('Порог закрытия должен быть ниже порога открытия.');
  }
  controls.gate_open?.setAttribute('aria-invalid', String(!controls.gate_open?.checkValidity() || !thresholdsValid));
  controls.gate_close?.setAttribute('aria-invalid', String(!controls.gate_close?.checkValidity() || !thresholdsValid));
  for (const key of ['silence_ms', 'pre_roll_ms']) {
    controls[key]?.setAttribute('aria-invalid', String(!controls[key]?.checkValidity()));
  }
  if (save) {
    save.disabled = !micCaptureWritable || micCaptureLoading || micCaptureSaving
      || !micCaptureDirty || !individuallyValid || !thresholdsValid || micCaptureNeedsReload;
    save.setAttribute('aria-busy', String(micCaptureSaving));
    save.textContent = micCaptureSaving ? 'Сохранение…' : 'Сохранить';
  }
  if (reload) {
    reload.hidden = !micCaptureNeedsReload;
    reload.disabled = !micCaptureWritable || micCaptureLoading || micCaptureSaving;
  }
}

async function waitForMicCaptureSession() {
  const deadline = Date.now() + 5_000;
  while (!API.csrf && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  return Boolean(API.csrf);
}

async function loadMicCaptureSettings() {
  const fieldset = document.querySelector('#mic-capture-fields');
  if (!fieldset) return;
  micCaptureLoading = true;
  setMicCaptureError('');
  setMicCaptureStatus('Загрузка настроек захвата…');
  updateMicCaptureControls();
  try {
    let response = await fetch('/api/voice/capture', {
      credentials: 'include', headers: API.headers(), signal: AbortSignal.timeout(5_000),
    });
    if (response.status === 403) {
      if (!API.csrf) await waitForMicCaptureSession();
      if (API.csrf) {
        response = await fetch('/api/voice/capture', {
          credentials: 'include', headers: API.headers(), signal: AbortSignal.timeout(5_000),
        });
      }
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok !== true) {
      micCaptureWritable = false;
      const reason = response.status === 503
        ? 'ConfigHub недоступен. Настройка захвата отключена.'
        : result.error || `HTTP ${response.status}`;
      setMicCaptureStatus(reason);
      if (response.status !== 503) setMicCaptureError(reason);
      return;
    }
    micCaptureWritable = result.settings_writable === true;
    micCaptureRevision = result.revision;
    const settings = result.settings || {};
    for (const [key, input] of Object.entries(micCaptureControls())) {
      if (input && settings[key] !== undefined) input.value = String(settings[key]);
    }
    micCaptureDirty = false;
    micCaptureNeedsReload = false;
    setMicCaptureError('');
    setMicCaptureStatus(micCaptureWritable
      ? 'Сохранённые значения. Изменения применяются при следующем запуске микрофона.'
      : 'ConfigHub недоступен. Параметры захвата отключены.');
  } catch (error) {
    micCaptureWritable = false;
    const reason = `Не удалось загрузить настройки захвата: ${error.message}`;
    setMicCaptureStatus(reason);
    setMicCaptureError(reason);
  } finally {
    micCaptureLoading = false;
    updateMicCaptureControls();
  }
}

async function saveMicCaptureSettings() {
  if (!micCaptureWritable || !micCaptureRevision || micCaptureSaving || !micCaptureDirty) return;
  const values = micCaptureValues();
  const controls = micCaptureControls();
  if (!Object.values(controls).every(input => input?.checkValidity())
      || values.gate_close >= values.gate_open) {
    setMicCaptureError('Проверьте диапазоны: порог закрытия должен быть ниже порога открытия.');
    updateMicCaptureControls();
    return;
  }

  micCaptureSaving = true;
  setMicCaptureError('');
  setMicCaptureStatus('Сохранение настроек…');
  updateMicCaptureControls();
  try {
    const response = await fetch('/api/voice/capture', {
      method: 'POST', credentials: 'include', headers: API.headers(),
      signal: AbortSignal.timeout(5_000),
      body: JSON.stringify({action: 'configure', settings: values, expected_revision: micCaptureRevision}),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok !== true) {
      if (response.status === 409) micCaptureNeedsReload = true;
      throw new Error(result.error || `HTTP ${response.status}`);
    }
    micCaptureRevision = result.revision;
    micCaptureDirty = false;
    setMicCaptureStatus('Сохранено. Новые значения применятся при следующем запуске микрофона.');
  } catch (error) {
    setMicCaptureError(`Не удалось сохранить настройки захвата: ${error.message}`);
    setMicCaptureStatus('Изменения не сохранены. Черновик оставлен в полях.');
  } finally {
    micCaptureSaving = false;
    updateMicCaptureControls();
  }
}

for (const input of Object.values(micCaptureControls())) {
  input?.addEventListener('input', () => {
    micCaptureDirty = true;
    setMicCaptureError('');
    setMicCaptureStatus('Есть несохранённые изменения.');
    updateMicCaptureControls();
  });
}
document.querySelector('#mic-capture-save')?.addEventListener('click', saveMicCaptureSettings);
document.querySelector('#mic-capture-reload')?.addEventListener('click', loadMicCaptureSettings);
loadMicCaptureSettings();
