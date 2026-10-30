import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../app.js', import.meta.url), 'utf8');

function createRenderer() {
  const elements = new Map();
  const document = {
    querySelector(selector) {
      const id = selector.slice(1);
      if (!elements.has(id)) elements.set(id, {textContent: '', dataset: {}, title: ''});
      return elements.get(id);
    },
  };
  const context = {document, state: {micActive: false}};
  const start = source.indexOf('function renderSensoryHealth(');
  const end = source.indexOf('\nasync function refreshJournal()', start);
  assert.ok(start >= 0 && end > start, 'renderSensoryHealth exists in app.js');
  vm.runInNewContext(`${source.slice(start, end)}\nglobalThis.render = renderSensoryHealth;`, context);
  return {render: context.render, elements};
}

test('sensor HUD reports active sources, freshness, and DND without calling DND an error', () => {
  const {render, elements} = createRenderer();
  render({
    ok: true,
    capture: {microphone_owner: 'desktop', loopback_configured: true, loopback_enabled: true, loopback_running: true, loopback_device: 'DigitalOutput (2- NVIDIA High Definition Audio) [Loopback]', loopback_device_index: 38, loopback_host_api_index: 2, loopback_sample_rate: 48000, loopback_channels: 2, loopback_last_chunk_age_ms: 400, loopback_signal_window_state: 'nonzero_pcm_unclassified', soundscape_configured: true, soundscape_count: 4, soundscape_errors: 0, soundscape_latency_ms_p95: 31, soundscape_last_kind: 'music', soundscape_last_tags: ['Saxophone'], soundscape_last_age_ms: 1400, soundscape_last_fresh: true},
    visual: {running: true, latest_age_ms: 2300, caption_fresh: true, caption_age_ms: 1700, capture_errors: 4, error_active: false},
    screen: {running: false},
    attention: {dnd: true, quiet_hours_active: false},
  });
  assert.equal(elements.get('sensor-mic').textContent, 'включён');
  assert.equal(elements.get('sensor-screen').textContent, 'описание актуально, 2 с');
  assert.equal(elements.get('sensor-loopback').textContent, 'PCM \u043f\u043e\u0441\u0442\u0443\u043f\u0430\u0435\u0442, \u0437\u0432\u0443\u043a \u043d\u0435 \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d');
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'YAMNet CPU: Музыка обнаружена · повторяющийся тег: Saxophone · 1 с назад · 4 сегм. · p95 31 ms');
  assert.equal(elements.get('sensor-soundscape-status').dataset.state, 'ok');
  assert.equal(elements.get('sensor-attention').textContent, 'не беспокоить');
  assert.equal(elements.get('sensor-attention').dataset.state, 'off');
  assert.equal(elements.get('sensory-health').dataset.state, 'warn');
  assert.notEqual(elements.get('sensory-health-compact').textContent, '');
  assert.equal(elements.get('sensory-health-compact').textContent.includes('1'), true);
  assert.equal(elements.get('sensory-health-compact').title.includes('Saxophone'), true);
  assert.equal(elements.get('sensory-health-compact').dataset.state, 'warn');
  assert.equal(elements.get('sensory-health-compact').title, elements.get('sensory-health').title);
});

test('sensor HUD marks stale perception and unavailable status honestly', () => {
  const {render, elements} = createRenderer();
  render({
    ok: true,
    capture: {loopback_configured: false},
    visual: {running: true, latest_age_ms: 9000, caption_fresh: false, caption_age_ms: 9000, capture_errors: 0},
    screen: {running: false},
    attention: {},
  });
  assert.equal(elements.get('sensor-screen').textContent, 'описание устарело, 9 с');
  assert.equal(elements.get('sensory-health').dataset.state, 'warn');
  assert.equal(elements.get('sensory-health-compact').dataset.state, 'warn');

  render({ok: false});
  assert.equal(elements.get('sensory-health').textContent, 'Статус сенсоров недоступен');
  assert.equal(elements.get('sensor-mic').dataset.state, 'error');
  assert.equal(elements.get('sensor-loopback-device').textContent, '\u0421\u0442\u0430\u0442\u0443\u0441 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u0430 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d');
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'Статус музыкального анализатора недоступен');
  assert.equal(elements.get('sensory-health-compact').dataset.state, 'error');
  assert.notEqual(elements.get('sensory-health-compact').textContent, '');
});

test('screen watcher without a caption sensor is shown as active, not stale', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {}, visual: {running: false}, screen: {running: true}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'наблюдатель активен');
  assert.equal(elements.get('sensor-screen').dataset.state, 'ok');
  assert.equal(elements.get('sensory-health').dataset.state, 'ok');
});

test('soundscape freshness abstains clearly and pause suppresses a previous music claim', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true, soundscape_configured: true,
    soundscape_count: 8, soundscape_errors: 0, soundscape_last_kind: 'unknown',
    soundscape_last_tags: [], soundscape_last_age_ms: 1200, soundscape_last_fresh: true,
  }, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'YAMNet CPU: Свежая проверка: музыка не подтверждена · 1 с назад · 8 сегм.');
  assert.equal(elements.get('sensor-soundscape-status').dataset.state, 'off');

  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true, loopback_paused: true,
    soundscape_configured: true, soundscape_count: 8, soundscape_errors: 0,
    soundscape_last_kind: 'music', soundscape_last_tags: ['Saxophone'],
    soundscape_last_age_ms: 1400, soundscape_last_fresh: true,
  }, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'YAMNet CPU: Анализ системного звука приостановлен · 8 сегм.');
  assert.equal(elements.get('sensor-soundscape-status').dataset.state, 'off');

  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true, soundscape_configured: true,
    soundscape_count: 8, soundscape_errors: 0, soundscape_last_kind: 'music',
    soundscape_last_tags: ['Saxophone'], soundscape_last_age_ms: 35000,
    soundscape_last_fresh: false,
  }, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-soundscape-status').textContent, 'YAMNet CPU: Нет свежей оценки музыки · последняя 35 с назад · 8 сегм.');
  assert.equal(elements.get('sensor-soundscape-status').dataset.state, 'warn');
});

test('screen capture age does not hide an expired semantic caption', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {}, visual: {running: true, latest_age_ms: 200, caption_fresh: false, caption_age_ms: 9000}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'описание устарело, 9 с');
  assert.equal(elements.get('sensor-screen').dataset.state, 'warn');
});

test('screen HUD distinguishes model caption age from same-scene confirmation age', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {}, visual: {
    running: true, latest_age_ms: 100, caption_fresh: true,
    caption_age_ms: 9000, caption_confirmed_age_ms: 1200,
  }, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'описание подтверждено, 1 с · модель 9 с');
});

test('running loopback without fresh chunks is waiting or stale, not hearing audio', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {loopback_configured: true, loopback_running: true}, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-loopback').textContent, '\u043f\u043e\u0442\u043e\u043a \u0437\u0430\u043f\u0443\u0449\u0435\u043d, \u0436\u0434\u0451\u0442 \u0434\u0430\u043d\u043d\u044b\u0435');
  assert.equal(elements.get('sensor-loopback').dataset.state, 'warn');
  assert.equal(elements.get('sensory-health').dataset.state, 'warn');
  render({ok: true, capture: {loopback_configured: true, loopback_running: true, loopback_last_chunk_age_ms: 7000}, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-loopback').textContent, 'нет новых чанков, 7 с');
  assert.equal(elements.get('sensor-loopback').dataset.state, 'warn');
});

test('fresh loopback callbacks with a full digital-zero window do not claim sound is received', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {
    loopback_configured: true, loopback_enabled: true, loopback_running: true,
    loopback_last_chunk_age_ms: 200, loopback_signal_window_state: 'digital_silence',
    loopback_signal_window_duration_ms: 1000, loopback_signal_window_rms: 0,
  }, visual: {}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-loopback').textContent, '\u0437\u0430\u0445\u0432\u0430\u0442 \u0430\u043a\u0442\u0438\u0432\u0435\u043d: \u0446\u0438\u0444\u0440\u043e\u0432\u044b\u0435 \u043d\u0443\u043b\u0438');
  assert.equal(elements.get('sensor-loopback').dataset.state, 'warn');
  assert.equal(elements.get('sensory-health-compact').textContent.includes('\u0431\u0435\u0437 \u0441\u0438\u0433\u043d\u0430\u043b\u0430'), true);
});

test('screen capture error clears when the sensor reports recovery', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {}, visual: {running: true, error_active: true}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'ошибка захвата');
  assert.equal(elements.get('sensory-health').dataset.state, 'error');

  render({ok: true, capture: {}, visual: {running: true, latest_age_ms: 400, caption_fresh: true, caption_age_ms: 300, error_active: false}, screen: {}, attention: {}});
  assert.equal(elements.get('sensor-screen').textContent, 'описание актуально, 0 с');
  assert.equal(elements.get('sensory-health').dataset.state, 'ok');
});

test('Qwen Omni audio status reports fresh processed media and latency without trusting model confidence', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true,
    audio_description_configured: true, audio_description_provider: 'qwen3-omni',
    audio_description_count: 3, audio_description_errors: 1, audio_description_skipped: 0,
    audio_description_latency_ms_p95: 940, audio_description_last_kind: 'music',
    audio_description_last_age_ms: 2500, audio_description_last_fresh: true,
  }, visual: {}, screen: {}, attention: {}});
  const status = elements.get('sensor-audio-description-status');
  assert.match(status.textContent, /Qwen3-Omni/);
  assert.match(status.textContent, /\u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442: \u043c\u0443\u0437\u044b\u043a\u0430/);
  assert.match(status.textContent, /3 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0439/);
  assert.match(status.textContent, /p95 940 ms/);
  assert.match(status.textContent, /\u043e\u0448\u0438\u0431\u043e\u043a 1/);
  // A fresh successful result demonstrates recovery after a previous error.
  assert.equal(status.dataset.state, 'ok');
});

test('Qwen Omni audio status distinguishes stale results and provider errors', () => {
  const {render, elements} = createRenderer();
  render({ok: true, capture: {
    loopback_configured: true, loopback_running: true,
    audio_description_configured: true, audio_description_provider: 'qwen3-omni',
    audio_description_count: 2, audio_description_errors: 1,
    audio_description_latency_ms_p95: 1100, audio_description_last_kind: 'unknown',
    audio_description_last_age_ms: 35000, audio_description_last_fresh: false,
  }, visual: {}, screen: {}, attention: {}});
  const status = elements.get('sensor-audio-description-status');
  assert.match(status.textContent, /\u043d\u0435\u0442 \u0441\u0432\u0435\u0436\u0435\u0433\u043e \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430/);
  assert.match(status.textContent, /\u043e\u0448\u0438\u0431\u043e\u043a 1/);
  assert.equal(status.dataset.state, 'warn');
});
