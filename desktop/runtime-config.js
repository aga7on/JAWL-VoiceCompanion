// Electron only consumes the control-port view; model execution stays in Python.
const fs = require('node:fs');
const path = require('node:path');

function port(value) {
  if (!Number.isInteger(value) || value < 1 || value > 65535 || value === 8765) {
    throw new Error('Invalid or reserved Companion control port');
  }
  return value;
}

function controlPort(repoRoot, env = process.env, files = fs) {
  const explicit = env.JAWL_DESKTOP_CONTROL_PORT;
  if (explicit !== undefined) {
    if (!/^\d{1,5}$/.test(explicit)) throw new Error('Invalid Companion control-port override');
    return port(Number(explicit));
  }
  function read(name, optional = false) {
    try {
      const filename = path.join(repoRoot, 'config', name);
      if (files.statSync(filename).size > 128 * 1024) throw new Error();
      const raw = files.readFileSync(filename, 'utf8');
      if (Buffer.byteLength(raw, 'utf8') > 128 * 1024) throw new Error();
      const data = JSON.parse(raw);
      if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error();
      if (data.ports !== undefined && (!data.ports || Array.isArray(data.ports) || typeof data.ports !== 'object')) throw new Error();
      return data;
    } catch (error) {
      if (optional && error.code === 'ENOENT') return {};
      throw new Error('Cannot read Companion runtime manifest');
    }
  }
  const base = read('runtime.manifest.json');
  const local = read('runtime.manifest.local.json', true);
  const ports = { ...base.ports, ...local.ports };
  const selected = port(ports.control);
  if (Object.entries(ports).some(([key, value]) => key !== 'control' && key !== 'reserved' && value === selected)) {
    throw new Error('Companion control port collides with another service');
  }
  if (Array.isArray(ports.reserved) && ports.reserved.includes(selected)) throw new Error('Reserved Companion control port');
  return selected;
}

module.exports = { controlPort };
