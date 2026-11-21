'use strict';
// Helper Node.js untuk adapter js: (JSON lines via stdin/stdout).
const readline = require('readline');
// Bridge JS berjalan sebagai proses terpisah, tetapi bukan sandbox OS. Modul yang
// memberi akses proses, filesystem, jaringan, loader dinamis, atau introspeksi
// sensitif harus ditolak secara default.
const DENY = new Set([
  'assert','async_hooks','child_process','cluster','dgram','diagnostics_channel',
  'dns','fs','http','http2','https','inspector','module','net','os','perf_hooks',
  'process','readline','repl','tls','trace_events','tty','v8','vm','wasi',
  'worker_threads'
]);
const MAX_RPC_LINE_BYTES = 1024 * 1024;
const MAX_HANDLES = 10000;
const MAX_ARGS = 1024;
const MAX_DEPTH = 12;
const MAX_ITEMS = 10000;
const MAX_BINARY_BYTES = 512 * 1024;
const H = new Map(); let nid = 1;
console.log = console.error;
function putHandle(value) {
  if (H.size >= MAX_HANDLES) throw new Error('batas handle JavaScript terlampaui');
  const id = nid++;
  if (!Number.isSafeInteger(id)) throw new Error('ruang ID handle JavaScript habis');
  H.set(id, value);
  return id;
}
function isData(v, d) {
  if (d > MAX_DEPTH) return false;
  if (v === null || v === undefined) return true;
  const ty = typeof v;
  if (ty === 'number' || ty === 'boolean' || ty === 'bigint') return true;
  if (ty === 'string') return Buffer.byteLength(v, 'utf8') <= MAX_RPC_LINE_BYTES;
  if (Array.isArray(v)) return v.length < MAX_ITEMS && v.every((x) => isData(x, d + 1));
  if (Buffer.isBuffer(v)) return v.length <= MAX_BINARY_BYTES;
  if (ty === 'object' && Object.getPrototypeOf(v) === Object.prototype) {
    const ks = Object.keys(v); return ks.length < MAX_ITEMS && ks.every((k) => Buffer.byteLength(k, 'utf8') <= 256 && isData(v[k], d + 1));
  }
  return false;
}
function enc(v, depth = 0) {
  if (v === null || v === undefined) return { t: 'n' };
  const ty = typeof v;
  if (ty === 'number') return Number.isFinite(v) ? { t: 'v', v } : { t: 'f', v: String(v) };
  if (ty === 'string' || ty === 'boolean') {
    if (ty === 'string' && Buffer.byteLength(v, 'utf8') > MAX_RPC_LINE_BYTES) {
      return { t: 'h', id: putHandle(v), k: 'obj' };
    }
    return { t: 'v', v };
  }
  if (ty === 'bigint') {
    const n = Number(v);
    if (!Number.isSafeInteger(n)) throw new Error('BigInt di luar rentang integer aman Qich/JSON');
    return { t: 'v', v: n };
  }
  // Bound recursion and container expansion. Deep/cyclic values become opaque handles.
  if (depth > MAX_DEPTH) return { t: 'h', id: putHandle(v), k: ty === 'function' ? 'fn' : 'obj' };
  if (Array.isArray(v)) {
    if (v.length >= MAX_ITEMS || depth === MAX_DEPTH) return { t: 'h', id: putHandle(v), k: 'obj' };
    return { t: 'a', v: v.map((x) => enc(x, depth + 1)) };
  }
  if (Buffer.isBuffer(v)) {
    if (v.length > MAX_BINARY_BYTES) return { t: 'h', id: putHandle(v), k: 'obj' };
    return { t: 'b', v: v.toString('base64') };
  }
  if (v && isData(v, depth)) { const o = Object.create(null); for (const k of Object.keys(v)) o[k] = enc(v[k], depth + 1); return { t: 'o', v: o }; }
  const id = putHandle(v); return { t: 'h', id, k: ty === 'function' ? 'fn' : 'obj' };
}
function dec(a) {
  switch (a.t) {
    case 'n': return null; case 'v': return a.v; case 'a': return a.v.map(dec);
    case 'o': { const o = Object.create(null); for (const k of Object.keys(a.v)) o[k] = dec(a.v[k]); return o; }
    case 'h': if (!H.has(a.id)) throw new Error('handle tidak valid'); return H.get(a.id);
    case 'b': return Buffer.from(a.v, 'base64');
  }
  throw new Error('nilai tidak dikenal');
}
function safeMemberName(name) {
  return typeof name === 'string' && name.length <= 256 && !name.startsWith('_') &&
    name !== 'constructor' && name !== 'prototype' && name !== '__proto__';
}
async function handle(r) {
  switch (r.op) {
    case 'import': {
      const raw = String(r.lib);
      const m = raw.replace(/^node:/, '').split('/')[0];
      if (DENY.has(m)) throw new Error('modul diblokir oleh kebijakan keamanan');
      return enc(require(raw));
    }
    case 'get': {
      if (!safeMemberName(r.name)) throw new Error('anggota diblokir oleh kebijakan keamanan');
      const o = H.get(r.id); if (o === undefined) throw new Error('handle tidak valid');
      const v = o[r.name]; if (typeof v === 'function') { const id = putHandle({ f: v, self: o, isFn: true }); return { t: 'h', id, k: 'fn' }; } return enc(v);
    }
    case 'call': { const e = H.get(r.id); if (e === undefined) throw new Error('handle tidak valid'); const args = r.args.map(dec); if (e && e.isFn) return enc(await e.f.apply(e.self, args)); return enc(await e(...args)); }
    case 'new': { const e = H.get(r.id); if (e === undefined) throw new Error('handle tidak valid'); const f = e && e.isFn ? e.f : e; return enc(new f(...r.args.map(dec))); }
    case 'free': H.delete(r.id); return { t: 'n' };
  }
  throw new Error('op tidak dikenal');
}
module.exports = { isData, enc, dec, safeMemberName, MAX_RPC_LINE_BYTES, MAX_HANDLES };

if (require.main === module) {
  function validateRequest(r) {
  if (!r || typeof r !== 'object' || Array.isArray(r)) throw new Error('request JS harus berupa objek');
  if (!Number.isSafeInteger(r.rid) || r.rid < 0) throw new Error('request ID JS tidak valid');
  if (typeof r.op !== 'string') throw new Error('operasi JS tidak valid');
  if (r.op === 'import') {
    if (typeof r.lib !== 'string' || !r.lib || r.lib.length > 256) throw new Error('nama modul JS tidak valid');
    if (r.lib.startsWith('.') || r.lib.startsWith('/') ||
        r.lib.includes(String.fromCharCode(92)) || r.lib.includes(String.fromCharCode(0))) {
      throw new Error('path modul lokal tidak diizinkan melalui bridge JS');
    }
  }
  if (['get', 'call', 'new', 'free'].includes(r.op) &&
      (!Number.isSafeInteger(r.id) || r.id <= 0)) throw new Error('ID handle JS tidak valid');
  if (r.op === 'get' && !safeMemberName(r.name)) throw new Error('anggota diblokir oleh kebijakan keamanan');
  if (r.op === 'call' || r.op === 'new') {
    if (!Array.isArray(r.args) || r.args.length > MAX_ARGS) throw new Error('jumlah argumen bridge JS tidak valid atau terlalu besar');
  }
}
function respond(rid, ok, value) {
  let line = ok
    ? JSON.stringify({ rid, ok: true, r: value })
    : JSON.stringify({ rid, ok: false, e: String(value && value.message || value || 'kesalahan JS') });
  if (Buffer.byteLength(line, 'utf8') > MAX_RPC_LINE_BYTES) {
    line = JSON.stringify({ rid, ok: false, e: 'respons bridge JS melampaui batas ukuran' });
  }
  process.stdout.write(line + '\n');
}
async function processLine(line) {
  if (Buffer.byteLength(line, 'utf8') > MAX_RPC_LINE_BYTES) {
    respond(null, false, 'request bridge JS melampaui batas ukuran');
    return;
  }
  let r;
  try { r = JSON.parse(line); }
  catch (_) { respond(null, false, 'JSON request JS tidak valid'); return; }
  const rid = r && typeof r === 'object' && !Array.isArray(r) &&
    Number.isSafeInteger(r.rid) && r.rid >= 0 ? r.rid : null;
  try {
    validateRequest(r);
    respond(rid, true, await handle(r));
  } catch (e) {
    respond(rid, false, e);
  }
}
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let chain = Promise.resolve();
rl.on('line', (line) => {
  chain = chain.then(() => processLine(line)).catch((e) => {
    process.stderr.write(String(e && e.message || e) + '\n');
  });
});
// Do not exit synchronously on close: queued requests must finish and stdout flush.
}