import test from 'node:test';
import assert from 'node:assert/strict';
import {consumeSpeechStream} from './speech-stream.js';

function wavBase64(duration = 0.2) {
  const sampleRate = 32000;
  const sampleCount = Math.round(sampleRate * duration);
  const wav = new ArrayBuffer(44 + sampleCount * 2);
  const view = new DataView(wav);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint32(40, sampleCount * 2, true);
  return Buffer.from(wav).toString('base64');
}

const audio = (index, duration = 0.2, extra = {}) => ({
  type: 'audio', index, media_type: 'audio/wav', data_base64: wavBase64(duration), ...extra,
});
const done = count => ({type: 'done', count});
const line = event => Buffer.from(JSON.stringify(event));

function responseFromBytes(parts) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(new Uint8Array(part));
      controller.close();
    },
  }), {headers: {'content-type': 'application/x-ndjson; charset=utf-8'}});
}

function responseFromEvents(events, {splitAt = null, trailingNewline = false} = {}) {
  const bytes = Buffer.from(events.map(JSON.stringify).join('\n') + (trailingNewline ? '\n' : ''));
  return responseFromBytes(splitAt === null
    ? [bytes]
    : [bytes.subarray(0, splitAt), bytes.subarray(splitAt)]);
}

class FakeAudioContext {
  currentTime = 0;
  destination = {};
  sources = [];
  async decodeAudioData(wav) {
    const view = new DataView(wav);
    return {duration: view.getUint32(40, true) / view.getUint32(28, true)};
  }
  createBufferSource() {
    const source = {
      connect() {},
      disconnect() { this.disconnected = true; },
      stop() { this.stopped = true; },
      start(when, offset = 0, duration = this.buffer.duration) {
        this.when = when;
        this.offset = offset;
        this.duration = duration;
        this.context.sources.push(this);
      },
      end() { this.onended?.(); },
      context: this,
    };
    return source;
  }
}

async function waitFor(predicate) {
  for (let i = 0; i < 100; i += 1) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.fail('condition did not become true');
}

function play(response, context, options = {}) {
  return consumeSpeechStream(response, {audioContext: context, ...options});
}

test('plays first ordered audio event before server sends done', async () => {
  const context = new FakeAudioContext();
  let controller;
  const response = new Response(new ReadableStream({
    start(value) {
      controller = value;
      value.enqueue(new Uint8Array(Buffer.concat([line(audio(0)), Buffer.from('\n')])));
    },
  }), {headers: {'content-type': 'application/x-ndjson'}});
  const task = play(response, context);
  await waitFor(() => context.sources.length === 1);
  assert.equal(context.sources[0].when, 0.12);
  context.sources[0].end();
  controller.enqueue(new Uint8Array(line(done(1))));
  controller.close();
  await task;
});

test('splits NDJSON across network boundaries and accepts a trailing unterminated line', async () => {
  const context = new FakeAudioContext();
  const bytes = Buffer.concat([line(audio(0)), Buffer.from('\n'), line(done(1))]);
  const task = play(responseFromBytes([bytes.subarray(0, 19), bytes.subarray(19, 57), bytes.subarray(57)]), context);
  await waitFor(() => context.sources.length === 1);
  context.sources[0].end();
  await task;
  assert.equal(context.sources.length, 1);
});

test('preserves UTF-8 metadata split inside a multibyte character', async () => {
  const context = new FakeAudioContext();
  const bytes = Buffer.concat([line(audio(0, 0.2, {text: 'Привет'})), Buffer.from('\n'), line(done(1))]);
  const splitAt = bytes.indexOf(Buffer.from('П')) + 1;
  const task = play(responseFromBytes([bytes.subarray(0, splitAt), bytes.subarray(splitAt)]), context);
  await waitFor(() => context.sources.length === 1);
  context.sources[0].end();
  await task;
  assert.equal(context.sources.length, 1);
});

test('rejects out-of-order indexes and corrupt base64/WAV events', async t => {
  for (const [name, events, code] of [
    ['out of order', [audio(1), done(1)], 'TTS_INVALID_AUDIO_EVENT'],
    ['base64', [{...audio(0), data_base64: '%%%='}, done(1)], 'TTS_INVALID_AUDIO'],
    ['WAV decode', [{...audio(0), data_base64: Buffer.from('not a wav payload').toString('base64')}, done(1)], 'TTS_INVALID_AUDIO'],
  ]) {
    await t.test(name, async () => {
      await assert.rejects(play(responseFromEvents(events), new FakeAudioContext()), {code});
    });
  }
});

test('surfaces in-band provider errors without parsing their message as audio', async () => {
  await assert.rejects(
    play(responseFromEvents([{type: 'error', error: 'private backend detail'}]), new FakeAudioContext()),
    {code: 'TTS_PROVIDER_ERROR'},
  );
});

test('rejects audio emitted after done and cleans up prior sources', async () => {
  const context = new FakeAudioContext();
  await assert.rejects(
    play(responseFromEvents([audio(0), done(1), audio(1)]), context),
    {code: 'TTS_EVENT_AFTER_DONE'},
  );
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].stopped, true);
  assert.equal(context.sources[0].disconnected, true);
});

test('enforces line and per-chunk duration limits', async t => {
  await t.test('oversized line', async () => {
    const oversized = Buffer.alloc(12 * 1024 * 1024 + 1, 32);
    await assert.rejects(play(responseFromBytes([oversized]), new FakeAudioContext()), {code: 'TTS_LIMIT_EXCEEDED'});
  });
  await t.test('oversized whitespace line terminated by newline', async () => {
    const oversized = Buffer.alloc(12 * 1024 * 1024 + 1, 32);
    const bytes = Buffer.concat([oversized, Buffer.from('\n'), line(done(0))]);
    await assert.rejects(play(responseFromBytes([bytes]), new FakeAudioContext()), {code: 'TTS_LIMIT_EXCEEDED'});
  });
  await t.test('oversized WAV duration', async () => {
    await assert.rejects(
      play(responseFromEvents([audio(0, 30.1), done(1)]), new FakeAudioContext()),
      {code: 'TTS_INVALID_WAV'},
    );
  });
});

test('rejects an oversized wire read before UTF-8 decoding without audio', async () => {
  const context = new FakeAudioContext();
  const oversized = new Uint8Array(64 * 1024 * 1024 + 1);
  oversized[0] = 0xff; // Decoding this read would instead fail with TTS_INVALID_UTF8.
  let cancelCalled = false;
  const response = new Response(new ReadableStream({
    start(controller) { controller.enqueue(oversized); },
    cancel() { cancelCalled = true; },
  }));
  await assert.rejects(play(response, context), {code: 'TTS_LIMIT_EXCEEDED'});
  assert.equal(cancelCalled, true);
  assert.equal(context.sources.length, 0);
});

test('counts short whitespace lines cumulatively across small wire chunks', async () => {
  const context = new FakeAudioContext();
  const chunk = Buffer.from((' '.repeat(1023) + '\n').repeat(64));
  let readCount = 0;
  let cancelCalled = false;
  const response = {ok: true, body: {getReader: () => ({
    read() {
      readCount += 1;
      if (readCount <= 1024) return Promise.resolve({done: false, value: chunk});
      if (readCount === 1025) return Promise.resolve({done: false, value: Buffer.from('\n')});
      if (readCount === 1026) return Promise.resolve({done: false, value: line(done(0))});
      return Promise.resolve({done: true});
    },
    cancel() { cancelCalled = true; return Promise.resolve(); },
  })}};
  await assert.rejects(play(response, context), {code: 'TTS_LIMIT_EXCEEDED'});
  assert.equal(readCount, 1025); // Exactly 64 MiB is accepted; the next byte is rejected.
  assert.equal(cancelCalled, true);
  assert.equal(context.sources.length, 0);
});

test('cancelled event and abort stop reading and ignore late events', async () => {
  await assert.rejects(play(responseFromEvents([{type: 'cancelled'}]), new FakeAudioContext()), {code: 'TTS_CANCELLED'});

  const context = new FakeAudioContext();
  const abort = new AbortController();
  let releaseLateRead;
  let readCount = 0;
  let cancelCalled = false;
  const lateDone = new Uint8Array(line(done(1)));
  const response = {ok: true, body: {getReader: () => ({
    read() {
      readCount += 1;
      if (readCount === 1) return Promise.resolve({done: false, value: new Uint8Array(Buffer.concat([line(audio(0)), Buffer.from('\n')]))});
      return new Promise(resolve => { releaseLateRead = () => resolve({done: false, value: lateDone}); });
    },
    cancel() { cancelCalled = true; releaseLateRead?.(); return Promise.resolve(); },
  })}};
  const task = play(response, context, {signal: abort.signal});
  await waitFor(() => context.sources.length === 1);
  abort.abort();
  await assert.rejects(task, {code: 'TTS_CANCELLED'});
  assert.equal(cancelCalled, true);
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].stopped, true);
  assert.equal(context.sources[0].disconnected, true);
});

test('keeps scheduled lead bounded and applies backpressure while the clock is stationary', async () => {
  const context = new FakeAudioContext();
  const response = responseFromEvents([audio(0, 0.4), audio(1, 0.4), audio(2, 0.4), done(3)]);
  const task = play(response, context);
  await waitFor(() => context.sources.length === 1);
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(context.sources.length, 1);
  context.currentTime = 0.12;
  await waitFor(() => context.sources.length === 2);
  context.currentTime = 0.52;
  await waitFor(() => context.sources.length === 3);
  assert.ok(context.sources.every(source => source.when + source.duration - context.currentTime <= 0.8));
  for (const source of [...context.sources]) source.end();
  await task;
});

test('segments a long decoded WAV so its scheduled tail never exceeds 0.8 seconds', async () => {
  const context = new FakeAudioContext();
  const task = play(responseFromEvents([audio(0, 30), done(1)]), context);
  let scheduled = 0;
  await waitFor(() => context.sources.length > scheduled);
  for (let i = 0; i < 75; i += 1) {
    const source = context.sources[i];
    if (!source) break;
    assert.ok(source.duration <= 0.4);
    assert.ok(source.when + source.duration - context.currentTime <= 0.8);
    scheduled = context.sources.length;
    context.currentTime = source.when + source.duration;
    for (const active of context.sources) {
      if (!active.ended && active.when + active.duration <= context.currentTime) {
        active.ended = true;
        active.end();
      }
    }
    await waitFor(() => context.sources.length > scheduled || i === 74);
  }
  for (const source of context.sources) if (!source.ended) source.end();
  await task;
  assert.equal(context.sources.length, 75);
});

test('rejects a stream that exceeds the deadline', async () => {
  const response = new Response(new ReadableStream({start() {}}));
  await assert.rejects(play(response, new FakeAudioContext(), {deadlineMs: 15}), {code: 'TTS_DEADLINE'});
});

test('deadline cancels a pending read and immediately stops already scheduled audio', async () => {
  const context = new FakeAudioContext();
  let cancelCalled = false;
  let readCount = 0;
  const response = {ok: true, body: {getReader: () => ({
    read() {
      readCount += 1;
      if (readCount === 1) return Promise.resolve({
        done: false,
        value: new Uint8Array(Buffer.concat([line(audio(0)), Buffer.from('\n')])),
      });
      return new Promise(() => {});
    },
    cancel() { cancelCalled = true; return Promise.resolve(); },
  })}};
  await assert.rejects(play(response, context, {deadlineMs: 20}), {code: 'TTS_DEADLINE'});
  assert.equal(cancelCalled, true);
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].stopped, true);
  assert.equal(context.sources[0].disconnected, true);
});

test('parser errors stop earlier sources and never leave scheduled audio behind', async () => {
  const context = new FakeAudioContext();
  const body = Buffer.concat([line(audio(0)), Buffer.from('\n{bad json}\n')]);
  await assert.rejects(play(responseFromBytes([body]), context), {code: 'TTS_INVALID_EVENT'});
  assert.equal(context.sources.length, 1);
  assert.equal(context.sources[0].stopped, true);
  assert.equal(context.sources[0].disconnected, true);
});
