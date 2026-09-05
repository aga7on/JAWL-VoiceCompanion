class JawlMicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(2048);
    this.offset = 0;
    this.port.onmessage = event => {
      if (event.data && event.data.type === 'flush') this.flush();
    };
  }

  flush() {
    if (!this.offset) {
      this.port.postMessage({type: 'flushed'});
      return;
    }
    const chunk = this.buffer.slice(0, this.offset);
    this.offset = 0;
    this.port.postMessage(chunk.buffer, [chunk.buffer]);
    this.port.postMessage({type: 'flushed'});
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    let offset = 0;
    while (offset < input.length) {
      const size = Math.min(input.length - offset, this.buffer.length - this.offset);
      this.buffer.set(input.subarray(offset, offset + size), this.offset);
      offset += size;
      this.offset += size;
      if (this.offset === this.buffer.length) {
        const chunk = this.buffer.slice();
        this.port.postMessage(chunk.buffer, [chunk.buffer]);
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor('jawl-mic-processor', JawlMicProcessor);
