import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const html = await readFile(new URL('../app.html', import.meta.url), 'utf8');

test('device selector and settings search have explicit accessible labels', () => {
  assert.match(html, /<label\b[^>]*for="mic-select"[^>]*>Устройство<\/label>/);
  assert.match(html, /<label\b[^>]*for="settings-search"[^>]*>Поиск по настройкам JAWL<\/label>/);
  assert.match(html, /#settings-search/);
  assert.match(html, /button:focus-visible, input:focus-visible, select:focus-visible/);
});

test('service status labels the JAWL brain without pinning a stale model name', () => {
  assert.match(html, /<span class="label">Мозг JAWL<\/span>\s*<span class="value" id="svc-brain">/);
  assert.doesNotMatch(html, /Мозг \(Hikari\)/);
});

test('service card explains its scope without implying that every service is healthy', () => {
  assert.match(html, /Список процессов и портов скрыт; здесь показывается состояние сервисов\./);
  assert.doesNotMatch(html, /всё работает в этом окне/);
});

test('system audio describer status is present and does not announce every polling update', () => {
  assert.match(html, /id="sensor-audio-description-status" role="status" aria-live="off"/);
});
