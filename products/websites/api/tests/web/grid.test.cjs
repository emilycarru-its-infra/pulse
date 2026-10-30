const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag, text = '') { this.tag = tag; this.text = text; this.children = []; this.attributes = {}; this.events = {}; }
  set textContent(text) { this.text = text; this.children = []; }
  get textContent() { return this.text + this.children.map(c => c.textContent).join(''); }
  get lastChild() { return this.children.at(-1); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ''; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
}
function page(hash = '') {
  const nodes = { groups: new Element('ul'), total: new Element('p'), picture: new Element('section') };
  const context = vm.createContext({ URL, URLSearchParams, Date,
    location: { href: 'https://status.example/' + hash, hash, pathname: '/', search: '' },
    history: { replaceState: (_, __, url) => { context.lastUrl = String(url); context.location.href = String(url); }, pushState: (_, __, url) => { context.lastUrl = String(url); context.location.href = String(url); } },
    document: { createElement: tag => new Element(tag), createTextNode: text => new Element('#text', text), getElementById: id => nodes[id] },
  });
  const source = readFileSync(path.join(__dirname, '../../../web/websites.js'), 'utf8');
  vm.runInContext(source.split('document.getElementById("filter").addEventListener')[0], context);
  const run = script => vm.runInContext(script, context);
  run(`data = { groups: [{id:'host-a',name:'Provider A'},{id:'host-b',name:'Provider B'}], websites:[
    {id:'z',name:'z.example.test',hostname:'z.example.test',url:'https://z.example.test/',group:'host-a',state:'down'},
    {id:'a',name:'a.example.test',hostname:'a.example.test',url:'https://a.example.test/',group:'host-b',state:'up'},
    {id:'path',name:'a.example.test/Art',hostname:'a.example.test',url:'https://a.example.test/Art/',group:'host-a',state:'unknown'}] };`);
  return {run, nodes, context};
}
test('website order is alphabetical across providers and health states', () => {
  const {run, nodes} = page();
  assert.equal(run('visibleWebsites().map(w => w.id).join(",")'), 'a,path,z');
  run('renderGroups()');
  assert.equal(nodes.groups.children.length, 3);
  assert.ok(nodes.groups.children.every(c => c.className === 'website-card'));
  assert.match(nodes.groups.children[0].textContent, /Provider B/);
  assert.equal(nodes.total.textContent, '3 websites · 1 up · 1 no data');
});
test('search, status and hosting filters intersect and update the visible count', () => {
  const {run, nodes} = page();
  run('Object.assign(ui,{place:"host-a",filter:"unknown",query:"art"}); renderGroups()');
  assert.equal(run('visibleWebsites().map(w => w.id).join(",")'), 'path');
  assert.equal(nodes.total.textContent, '1 of 3 websites · 0 up · 1 no data');
});
test('deep links expand a website in place without changing alphabetical order', () => {
  const {run,nodes,context} = page('#site=path');
  run('renderGroups()');
  assert.equal(nodes.groups.children[1].children[0].attributes['aria-expanded'], 'true');
  assert.match(nodes.groups.children[1].textContent, /https:\/\/a.example.test\/Art\//);
  run('pick("z")');
  assert.equal(new URL(context.lastUrl).searchParams.get('site'), 'z');
  assert.equal(nodes.groups.children[2].children[0].attributes['aria-expanded'], 'true');
  assert.equal(run('visibleWebsites().map(w => w.id).join(",")'), 'a,path,z');
});
test('network tags remain searchable and missing checks are explained', () => {
  const {run,nodes} = page();
  run('Object.assign(data.websites[2],{name:"Art",network:"Network"}); ui.query="network"; renderGroups()');
  assert.equal(nodes.groups.children.length, 1);
  assert.match(nodes.groups.children[0].textContent, /ArtProvider ANetwork/);
  assert.match(nodes.groups.children[0].textContent, /No individual check received/);
  run('pick("path")');
  assert.match(nodes.groups.children[0].textContent, /https:\/\/a.example.test\/Art\//);
});

test('overview includes counted network filters and intersects them with hosting and health', () => {
  const {run,nodes} = page();
  run('data.websites[0].network="Network"; data.websites[2].network="Network"; renderPicture()');
  const button = nodes.picture.children.find(b => b.textContent === 'Network2');
  assert.ok(button);
  assert.equal(button.attributes['aria-pressed'], 'false');
  run('ui.network="Network"; renderPicture(); renderGroups()');
  assert.equal(nodes.picture.children[0].attributes['aria-pressed'], 'true');
  assert.equal(run('visibleWebsites().length'), 2);
  run('ui.filter="unknown"; ui.place="host-a"; renderGroups()');
  assert.equal(run('visibleWebsites().map(w => w.id).join(",")'), 'path');
  run('ui.place="host-b"; renderGroups()');
  assert.equal(run('visibleWebsites().length'), 0);
  run('ui.network=null; ui.filter="all"; renderGroups()');
  assert.equal(run('visibleWebsites().map(w => w.id).join(",")'), 'a');
});
test('shared versions are labelled and link to parent analytics', () => {
  const {run,nodes} = page('#site=path');
  run('data.websites[2].hosting={name:"Network",website_id:"a",facts:{php_version:"8.3",wordpress_version:"7.0"}}; renderGroups()');
  const card = nodes.groups.children.find(c => c.textContent.includes('a.example.test/Art'));
  assert.match(card.textContent, /PHP 8.3/);
  assert.match(card.textContent, /Shared Network hosting/);
  assert.match(card.textContent, /View shared installation analytics/);
  assert.doesNotMatch(card.textContent, /100 visits/);
});
test('website dropdowns, search and status round-trip in shared URLs and clear together', () => {
  const {run,context} = page();
  run('Object.assign(ui,{place:"host-a",network:"Network",php:"8.3",wordpress:"7.1",query:"art",filter:"unknown",picked:"path"}); writeFilters()');
  const restored = page(new URL(context.lastUrl).search);
  for (const [key,value] of Object.entries({place:'host-a',network:'Network',php:'8.3',wordpress:'7.1',query:'art',filter:'unknown',picked:'path'}))
    assert.equal(restored.run(`ui.${key}`),value);
  assert.equal(restored.run('hasFilters()'),true);
  restored.run('clearFilters(); writeFilters()');
  assert.equal(restored.run('hasFilters()'),false);
  assert.equal(new URL(restored.context.lastUrl).search,'');
});
