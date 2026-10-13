const MAX_LINE_CHARS = 12 * 1024 * 1024;
const MAX_AUDIO_BYTES = 8 * 1024 * 1024;
const MAX_TOTAL_AUDIO_BYTES = 32 * 1024 * 1024;
const MAX_TOTAL_WIRE_BYTES = 64 * 1024 * 1024;
const MAX_AUDIO_EVENTS = 512;
const MAX_CHUNK_SECONDS = 30;
const MAX_TOTAL_SECONDS = 300;
const MAX_SCHEDULED_AHEAD_SECONDS = 0.8;
const MAX_SLICE_SECONDS = 0.4;
const INITIAL_LEAD_SECONDS = 0.12;
const STREAM_DEADLINE_MS = 120_000;

function streamError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function decodeBase64(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > Math.ceil(MAX_AUDIO_BYTES * 4 / 3) + 4
      || value.length % 4 !== 0 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    throw streamError('TTS_INVALID_AUDIO');
  }
  const binary = atob(value);
  if (binary.length < 44 || binary.length > MAX_AUDIO_BYTES) throw streamError('TTS_INVALID_AUDIO');
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function abortableDelay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(streamError('TTS_CANCELLED'));
    const timer = setTimeout(done, ms);
    function done() {
      signal.removeEventListener('abort', abort);
      resolve();
    }
    function abort() {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      reject(streamError('TTS_CANCELLED'));
    }
    signal.addEventListener('abort', abort, {once: true});
  });
}

/** Consume sentence-WAV NDJSON with bounded memory and an actual bounded audio horizon. */
export async function consumeSpeechStream(response, {
  audioContext,
  signal,
  isCurrent = () => true,
  connectSource = source => source.connect(audioContext.destination),
  onSourceStart = () => {},
  onSourceEnd = () => {},
  onStreamDone = () => {},
  deadlineMs = STREAM_DEADLINE_MS,
} = {}) {
  if (!response?.ok || !response.body?.getReader || !audioContext?.decodeAudioData) {
    throw streamError('TTS_STREAM_UNAVAILABLE');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', {fatal: true});
  const sessionController = new AbortController();
  const sources = new Set();
  let pending = '';
  let expectedIndex = 0;
  let totalBytes = 0;
  let totalWireBytes = 0;
  let totalSeconds = 0;
  let nextStart = audioContext.currentTime + INITIAL_LEAD_SECONDS;
  let streamDone = false;
  let interrupted = false;
  let rejectInterruption;
  let deadlineTimer;
  let rejectPromise;
  const interruption = new Promise((_, reject) => { rejectInterruption = reject; });
  void interruption.catch(() => {});

  const isLive = () => !interrupted && !sessionController.signal.aborted && !signal?.aborted && isCurrent();
  const stopSources = () => {
    for (const source of sources) {
      source.onended = null;
      try { source.stop(); } catch {}
      try { source.disconnect(); } catch {}
      try { onSourceEnd(source); } catch {}
    }
    sources.clear();
  };
  const interrupt = error => {
    if (interrupted) return;
    interrupted = true;
    sessionController.abort();
    stopSources();
    void reader.cancel().catch(() => {});
    rejectInterruption(error);
    rejectPromise?.(error);
  };
  const onAbort = () => interrupt(streamError('TTS_CANCELLED'));
  signal?.addEventListener('abort', onAbort, {once: true});
  if (signal?.aborted) onAbort();
  deadlineTimer = setTimeout(() => interrupt(streamError('TTS_DEADLINE')), deadlineMs);

  const isStillCurrent = () => {
    if (!isLive()) throw streamError('TTS_CANCELLED');
  };

  const scheduleAudio = async event => {
    if (event.index !== expectedIndex || !Number.isSafeInteger(event.index)
        || event.media_type !== 'audio/wav' || typeof event.data_base64 !== 'string') {
      throw streamError('TTS_INVALID_AUDIO_EVENT');
    }
    if (++expectedIndex > MAX_AUDIO_EVENTS) throw streamError('TTS_LIMIT_EXCEEDED');
    const wav = decodeBase64(event.data_base64);
    totalBytes += wav.byteLength;
    if (totalBytes > MAX_TOTAL_AUDIO_BYTES) throw streamError('TTS_LIMIT_EXCEEDED');
    isStillCurrent();

    let buffer;
    try {
      buffer = await Promise.race([audioContext.decodeAudioData(wav), interruption]);
    } catch (error) {
      if (error?.code) throw error;
      throw streamError('TTS_INVALID_WAV');
    }
    isStillCurrent();
    if (!Number.isFinite(buffer?.duration) || buffer.duration <= 0 || buffer.duration > MAX_CHUNK_SECONDS) {
      throw streamError('TTS_INVALID_WAV');
    }
    totalSeconds += buffer.duration;
    if (totalSeconds > MAX_TOTAL_SECONDS) throw streamError('TTS_LIMIT_EXCEEDED');

    const sliceCount = Math.ceil(buffer.duration / MAX_SLICE_SECONDS);
    for (let sliceIndex = 0; sliceIndex < sliceCount; sliceIndex += 1) {
      const offset = sliceIndex * MAX_SLICE_SECONDS;
      const duration = Math.min(MAX_SLICE_SECONDS, buffer.duration - offset);
      while (nextStart - audioContext.currentTime + duration > MAX_SCHEDULED_AHEAD_SECONDS) {
        isStillCurrent();
        const excess = nextStart - audioContext.currentTime + duration - MAX_SCHEDULED_AHEAD_SECONDS;
        await abortableDelay(Math.min(100, Math.max(20, excess * 1000)), sessionController.signal);
      }
      isStillCurrent();

      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      connectSource(source);
      sources.add(source);
      source.onended = () => {
        sources.delete(source);
        try { source.disconnect(); } catch {}
        try { onSourceEnd(source); } catch {}
      };
      const startAt = Math.max(nextStart, audioContext.currentTime + 0.01);
      source.start(startAt, offset, duration);
      nextStart = startAt + duration;
      try { onSourceStart(source, startAt, duration); } catch {}
    }
  };

  const consumeLine = async line => {
    if (line.length > MAX_LINE_CHARS) throw streamError('TTS_LIMIT_EXCEEDED');
    if (!line.trim()) return;
    if (streamDone) throw streamError('TTS_EVENT_AFTER_DONE');
    let event;
    try { event = JSON.parse(line); } catch { throw streamError('TTS_INVALID_EVENT'); }
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw streamError('TTS_INVALID_EVENT');
    if (event.type === 'audio') return scheduleAudio(event);
    if (event.type === 'cancelled') throw streamError('TTS_CANCELLED');
    if (event.type === 'error') throw streamError('TTS_PROVIDER_ERROR');
    if (event.type === 'done') {
      if (event.count !== expectedIndex) throw streamError('TTS_INVALID_DONE');
      streamDone = true;
      return;
    }
    throw streamError('TTS_INVALID_EVENT');
  };

  const consume = async () => {
    try {
      while (true) {
        isStillCurrent();
        const result = await Promise.race([reader.read(), interruption]);
        isStillCurrent();
        totalWireBytes += result.value?.byteLength ?? 0;
        if (totalWireBytes > MAX_TOTAL_WIRE_BYTES) throw streamError('TTS_LIMIT_EXCEEDED');
        try {
          pending += decoder.decode(result.value || new Uint8Array(), {stream: !result.done});
        } catch {
          throw streamError('TTS_INVALID_UTF8');
        }
        if (pending.length > MAX_LINE_CHARS && !pending.includes('\n')) throw streamError('TTS_LIMIT_EXCEEDED');
        const lines = pending.split('\n');
        pending = lines.pop() || '';
        for (const line of lines) await consumeLine(line);
        if (result.done) break;
      }
      await consumeLine(pending);
      if (!streamDone) throw streamError('TTS_TRUNCATED');
      while (sources.size > 0) {
        isStillCurrent();
        await abortableDelay(25, sessionController.signal);
      }
      isStillCurrent();
      clearTimeout(deadlineTimer);
      signal?.removeEventListener('abort', onAbort);
      onStreamDone();
    } catch (error) {
      interrupt(error?.code ? error : streamError('TTS_PLAYBACK_FAILED'));
      clearTimeout(deadlineTimer);
      signal?.removeEventListener('abort', onAbort);
      throw error?.code ? error : streamError('TTS_PLAYBACK_FAILED');
    }
  };

  const result = new Promise((resolve, reject) => {
    rejectPromise = reject;
    void consume().then(resolve, reject);
  });
  return result;
}
