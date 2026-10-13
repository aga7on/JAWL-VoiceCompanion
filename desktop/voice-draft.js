const DEFAULT_TIMEOUT_MS = 4000;
const MAX_TIMEOUT_MS = 30_000;
const MAX_DRAFT_CHARS = 2000;
const NO_DISPATCH = Symbol('voice-draft-no-dispatch');

function readIdentity(snapshot) {
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) return null;
  const {session_id, correlation_id, capture_id, generation} = snapshot;
  if (typeof session_id !== 'string' || !session_id.trim()
      || typeof correlation_id !== 'string' || !correlation_id.trim()
      || typeof capture_id !== 'string' || !capture_id.trim()
      || !Number.isSafeInteger(generation) || generation < 0
      || snapshot.active === false || snapshot.heard === false || snapshot.finalizing === true) {
    return null;
  }
  return Object.freeze({session_id, correlation_id, capture_id, generation});
}

function sameIdentity(left, right) {
  return Boolean(left && right
    && left.session_id === right.session_id
    && left.correlation_id === right.correlation_id
    && left.capture_id === right.capture_id
    && left.generation === right.generation);
}

/**
 * Bounded poller for POST /api/voice/draft. request(payload, signal) is supplied
 * by the caller so it can provide its normal auth headers and credentials.
 * Snapshot shape: {session_id, correlation_id, capture_id, generation};
 * getCurrent returns null unless the mic is active, heard, and not finalizing.
 *
 * Integration sketch:
 *   const drafts = createVoiceDraftController({
 *     getCurrent: () => activeHeardUtteranceSnapshotOrNull(),
 *     request: (payload, signal) => postVoiceDraft(payload, signal),
 *     onDraft: (text, identity) => renderTransientDraft(text, identity),
 *   });
 *   // Call tick from the existing bounded poll timer; pause/finalize/reset/stop
 *   // with the mic lifecycle. Draft text is transient and is never persisted.
 */
export function createVoiceDraftController({
  request,
  getCurrent,
  onDraft = () => {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
} = {}) {
  if (typeof request !== 'function' || typeof getCurrent !== 'function') {
    throw new TypeError('voice draft controller requires request and getCurrent functions');
  }
  if (typeof onDraft !== 'function' || typeof setTimer !== 'function' || typeof clearTimer !== 'function') {
    throw new TypeError('invalid voice draft callback or timer functions');
  }
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > MAX_TIMEOUT_MS) {
    throw new RangeError(`timeoutMs must be a finite number between 1 and ${MAX_TIMEOUT_MS}`);
  }
  const deadlineMs = timeoutMs;

  let paused = false;
  let stopped = false;
  let epoch = 0;
  let lastIdentity = null;
  let renderedText = '';
  let inflight = null;

  function clearDraft() {
    if (!renderedText) return;
    const identity = lastIdentity;
    renderedText = '';
    try { onDraft('', identity); } catch { /* presentation failure must not stop capture */ }
  }

  function invalidate() {
    epoch += 1;
    clearDraft();
    if (inflight && !inflight.controller.signal.aborted) {
      try { inflight.controller.abort(); } catch { /* abort is best effort */ }
    }
  }

  function currentIdentity() {
    let snapshot;
    try { snapshot = getCurrent(); } catch { return null; }
    return readIdentity(snapshot);
  }

  function isEligible(attempt) {
    return !paused && !stopped && !attempt.timedOut
      && inflight === attempt && epoch === attempt.epoch
      && sameIdentity(attempt.identity, currentIdentity());
  }

  function settleAttempt(attempt) {
    if (attempt.timer !== null) {
      try { clearTimer(attempt.timer); } catch { /* timer cleanup is best effort */ }
      attempt.timer = null;
    }
    attempt.settled = true;
    if (inflight === attempt) inflight = null;
  }

  async function tick() {
    if (stopped || paused) return {status: stopped ? 'stopped' : 'paused'};

    const identity = currentIdentity();
    if (!identity) {
      if (lastIdentity || renderedText || inflight) invalidate();
      lastIdentity = null;
      return {status: 'inactive'};
    }
    if (!sameIdentity(identity, lastIdentity)) {
      invalidate();
      lastIdentity = identity;
    }
    if (inflight) return {status: 'busy'};

    const controller = new AbortController();
    const attempt = {controller, identity, epoch, timer: null, settled: false, timedOut: false};
    inflight = attempt;
    let resolveOutcome;
    const outcome = new Promise(resolve => { resolveOutcome = resolve; });
    const complete = result => {
      settleAttempt(attempt);
      resolveOutcome(result);
    };

    attempt.timer = setTimer(() => {
      if (attempt.settled || attempt.timedOut) return;
      attempt.timedOut = true;
      clearDraft();
      try { controller.abort(); } catch { /* timeout still fences the result */ }
      resolveOutcome({status: 'timeout'});
    }, deadlineMs);

    // The slot is released only by this request's actual settlement. An
    // endpoint that ignores AbortSignal therefore cannot spawn overlapping polls.
    Promise.resolve()
      .then(() => {
        // Lifecycle methods can run synchronously before this microtask. Fence
        // there as well as after the response so cancellation prevents dispatch.
        if (!isEligible(attempt) || controller.signal.aborted) {
          complete({status: 'stale'});
          return NO_DISPATCH;
        }
        return request({
          session_id: identity.session_id,
          correlation_id: identity.correlation_id,
          owner: 'desktop',
          capture_id: identity.capture_id,
        }, controller.signal);
      })
      .then(response => {
        if (response === NO_DISPATCH) return;
        if (!isEligible(attempt)) {
          clearDraft();
          if (attempt.timedOut) return;
          complete({status: 'stale'});
          return;
        }
        if (!response || response.ok !== true || response.status === 'cancelled'
            || response.mode === 'unavailable' || response.mode !== 'streaming'
            || typeof response.draft !== 'string') {
          clearDraft();
          complete({status: response?.status === 'cancelled' ? 'cancelled' : 'unavailable'});
          return;
        }
        const text = response.draft.slice(0, MAX_DRAFT_CHARS);
        if (text !== renderedText) {
          renderedText = text;
          try { onDraft(text, identity); } catch { /* presentation failure is isolated */ }
        }
        complete({status: 'updated', draft: text});
      })
      .catch(() => {
        if (isEligible(attempt)) clearDraft();
        complete({status: isEligible(attempt) ? 'error' : 'stale'});
      })
      .finally(() => settleAttempt(attempt));

    return outcome;
  }

  function pause() {
    paused = true;
    invalidate();
  }

  function resume() {
    if (!stopped) paused = false;
  }

  function finalize() {
    paused = true;
    invalidate();
  }

  function reset() {
    invalidate();
    lastIdentity = null;
  }

  function stop() {
    stopped = true;
    paused = true;
    invalidate();
    lastIdentity = null;
  }

  return Object.freeze({tick, pause, resume, finalize, reset, stop, invalidate});
}

export {DEFAULT_TIMEOUT_MS as VOICE_DRAFT_TIMEOUT_MS, MAX_DRAFT_CHARS as VOICE_DRAFT_MAX_CHARS};
