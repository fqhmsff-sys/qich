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
const H = new Map(); let nid = 1;
console.log = console.error;
function isData(v, d) {
  if (d > 12) return false;
  if (v === null || v === undefined) return true;
  const ty = typeof v;
  if (ty === 'number' || ty === 'string' || ty === 'boolean' || ty === 'bigint') return true;
  if (Array.isArray(v)) return v.length < 10000 && v.every((x) => isData(x, d + 1));
  if (Buffer.isBuffer(v)) return true;
  if (ty === 'object' && Object.getPrototypeOf(v) === Object.prototype) {
    const ks = Object.keys(v); return ks.length < 10000 && ks.every((k) => isData(v[k], d + 1));
  }
  return false;
}
function enc(v) {
  if (v === null || v === undefined) return { t: 'n' };
  const ty = typeof v;
  if (ty === 'number') return Number.isFinite(v) ? { t: 'v', v } : { t: 'f', v: String(v) };
  if (ty === 'string' || ty === 'boolean') return { t: 'v', v };
  if (ty === 'bigint') {
    const n = Number(v);
    if (!Number.isSafeInteger(n)) throw new Error('BigInt di luar rentang integer aman Qich/JSON');
    return { t: 'v', v: n };
  }
  if (Array.isArray(v)) return { t: 'a', v: v.map(enc) };
  if (Buffer.isBuffer(v)) return { t: 'b', v: v.toString('base64') };
  if (v && isData(v, 0)) { const o = {}; for (const k of Object.keys(v)) o[k] = enc(v[k]); return { t: 'o', v: o }; }
  const id = nid++; H.set(id, v); return { t: 'h', id, k: ty === 'function' ? 'fn' : 'obj' };
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
  return typeof name === 'string' && !name.startsWith('_') &&
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
      const v = o[r.name]; if (typeof v === 'function') { const id = nid++; H.set(id, { f: v, self: o, isFn: true }); return { t: 'h', id, k: 'fn' }; } return enc(v);
    }
    case 'call': { const e = H.get(r.id); if (e === undefined) throw new Error('handle tidak valid'); const args = r.args.map(dec); if (e && e.isFn) return enc(await e.f.apply(e.self, args)); return enc(await e(...args)); }
    case 'new': { const e = H.get(r.id); if (e === undefined) throw new Error('handle tidak valid'); const f = e && e.isFn ? e.f : e; return enc(new f(...r.args.map(dec))); }
    case 'free': H.delete(r.id); return { t: 'n' };
  }
  throw new Error('op tidak dikenal');
}
const rl = readline.createInterface({ input: process.stdin });
let chain = Promise.resolve();
rl.on('line', (line) => {
  chain = chain.then(async () => {
    let r;
    try { r = JSON.parse(line); } catch (e) { return; }
    try { process.stdout.write(JSON.stringify({ rid: r.rid, ok: true, r: await handle(r) }) + '\n'); }
    catch (e) { process.stdout.write(JSON.stringify({ rid: r.rid, ok: false, e: String(e && e.message || e) }) + '\n'); }
  });
});
rl.on('close', () => process.exit(0));
