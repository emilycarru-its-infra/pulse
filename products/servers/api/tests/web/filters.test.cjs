const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function page(url = 'https://status.example/', savedView = null) {
  const events = {};
  const context = vm.createContext({
    URL, URLSearchParams,
    location: { href: url, hash: new URL(url).hash },
    localStorage: { getItem: () => savedView },
    window: { addEventListener: (name, callback) => { events[name] = callback; } },
    history: {
      pushState: (_, __, next) => { context.location.href = next.href; },
      replaceState: (_, __, next) => { context.location.href = next.href; },
    },
  });
  const source = readFileSync(path.join(__dirname, '../../../web/servers.js'), 'utf8');
  vm.runInContext(source.split('const focusVeil =')[0], context);
  return { run: (script) => vm.runInContext(script, context), events };
}

test('platform families and missing OS are selectable without guessing a version', () => {
  const { run } = page();
  for (const [os, platform] of [['Windows Server 2025', 'Windows'], ['Ubuntu 24.04', 'Linux'],
    ['Amazon Linux 2023.10', 'Linux'], ['macOS 15.1', 'macOS'], ['FreeBSD 14.2', 'BSD'],
    ['Custom OS', 'Other'], [null, 'Unknown']]) {
    assert.equal(run(`serverPlatform({os: ${JSON.stringify(os)}})`), platform);
  }
  run('ui.platform = "Unknown"; ui.os = "unknown"');
  assert.equal(run('matches({os: null})'), true);
  assert.equal(run('matches({os: "Ubuntu 24.04"})'), false);
});

test('OS, binary, status, location and search filters intersect', () => {
  const { run } = page();
  run(`data = {serviceNames: {}};
    Object.assign(ui, {platform: 'Linux', os: 'Ubuntu 24.04', runtime: 'Python', binaryVersion: '3.12', filter: 'degraded', place: 'cloud', query: 'worker'});
    globalThis.server = {os: 'Ubuntu 24.04', state: 'degraded', location: 'cloud', name: 'Worker', id: 'worker-1', runtimeInventory: {freshness: 'fresh', components: [{name: 'Python', version: '3.12'}]}};`);
  assert.equal(run('matches(server)'), true);
  for (const patch of [{os: 'Ubuntu 22.04'}, {state: 'up'}, {location: 'rack'}, {name: 'Web', id: 'web-1'},
    {runtimeInventory: {freshness: 'stale', components: [{name: 'Python', version: '3.12'}]}}]) {
    assert.equal(run(`matches({...server, ...${JSON.stringify(patch)}})`), false);
  }
});

test('combined URL round trips and history restores cleared filters', () => {
  const { run, events } = page('https://status.example/?unrelated=keep#server=worker-1');
  assert.equal(run('ui.picked'), 'worker-1');
  run(`Object.assign(ui, {platform: 'Linux', os: 'Ubuntu 24.04', runtime: 'Python', binaryVersion: '3.12', view: 'service', filter: 'degraded', place: 'cloud', query: 'worker'}); writeBinaryUrl();`);
  const url = run('location.href');
  const restored = page(url);
  for (const [key, value] of Object.entries({platform: 'Linux', os: 'Ubuntu 24.04', runtime: 'Python', binaryVersion: '3.12', view: 'service', filter: 'degraded', place: 'cloud', query: 'worker', picked: 'worker-1'})) {
    assert.equal(restored.run(`ui.${key}`), value);
  }
  assert.equal(new URL(url).searchParams.get('unrelated'), 'keep');
  assert.equal(new URL(url).hash, '');
  run('location.href = "https://status.example/"; location.hash = ""');
  events.popstate();
  for (const key of ['platform', 'os', 'runtime', 'binaryVersion', 'picked', 'place']) assert.equal(run(`ui.${key}`), null);
  assert.equal(run('ui.view'), 'location');
  assert.equal(run('ui.filter'), 'all');
});

test('legacy binary links and saved group preference still load', () => {
  const { run } = page('https://status.example/?binary=Python&version=3.12', 'service');
  assert.equal(run('ui.runtime'), 'Python');
  assert.equal(run('ui.binaryVersion'), '3.12');
  assert.equal(run('ui.view'), 'service');
});
test('any selected filter enables results mode and clearing restores the overview', () => {
  const {run} = page('https://status.example/?os=Ubuntu+24.04&binary=Python&version=3.12&q=worker&view=service');
  assert.equal(run('hasFilters()'),true);
  run('clearFilters(); writeBinaryUrl()');
  assert.equal(run('hasFilters()'),false);
  assert.equal(run('ui.view'),'service');
  const url = new URL(run('location.href'));
  assert.equal(url.searchParams.get('view'),'service');
  for (const name of ['os','binary','version','q','status','location','platform']) assert.equal(url.searchParams.has(name),false);
});

test('kernel patch links round trip and clearing removes patching mode', () => {
  const {run} = page('https://status.example/?mode=patching&cve=CVE-2026-12345&patch=restart_required');
  assert.equal(run('ui.patching'), true);
  assert.equal(run('ui.cve'), 'CVE-2026-12345');
  assert.equal(run('ui.patchState'), 'restart_required');
  run('writeBinaryUrl()');
  assert.equal(new URL(run('location.href')).searchParams.get('patch'), 'restart_required');
  run('clearFilters(); writeBinaryUrl()');
  assert.equal(new URL(run('location.href')).searchParams.has('cve'), false);
  assert.equal(run('hasFilters()'), false);
});

test('patching intersects filters, excludes non-applicable platforms and keeps missing evidence unknown', () => {
  const {run} = page('https://status.example/?cve=CVE-2026-12345&patch=unknown');
  run('data={serviceNames:{}}');
  assert.equal(run('matches({name:"worker", id:"w", patches:[]})'), true);
  assert.equal(run('matches({patches:[{cve:"CVE-2026-12345",state:"not_affected",applicable:false}]})'), false);
  assert.equal(run('matches({patches:[{cve:"CVE-2026-12345",state:"verified_fixed",applicable:true}]})'), false);
  run('ui.patchState="needs_patch";ui.platform="Linux"');
  assert.equal(run('matches({os:"Ubuntu 24.04",patches:[{cve:"CVE-2026-12345",state:"needs_patch",applicable:true}]})'), true);
});
