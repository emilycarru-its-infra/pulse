const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag, text = '') { this.tag = tag; this.text = text; this.children = []; this.attributes = {}; this.events = {}; this.dataset = {}; this.style = {setProperty() {}}; }
  set textContent(text) { this.text = text; this.children = []; }
  get textContent() { return this.text + this.children.map(c => c.textContent).join(''); }
  get lastChild() { return this.children.at(-1); }
  get firstElementChild() { return this.children[0]; }
  get childNodes() { return this.children; }
  getAttribute(key) { return this.attributes[key]; }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; }
  insertBefore(child, reference) { child.remove(); const i = reference ? this.children.indexOf(reference) : this.children.length; this.children.splice(i, 0, child); child.parent = this; }
  append(...children) { for (const child of children) { child.remove(); child.parent = this; this.children.push(child); } }
  replaceChildren(...children) { for (const child of [...this.children]) child.remove(); this.children = []; this.text = ''; this.append(...children); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
}
function page(hash = '') {
  const nodes = { groups: new Element('ul'), total: new Element('p'), picture: new Element('section'), hosting: new Element('select'), network: new Element('select') };
  const context = vm.createContext({ URL, URLSearchParams, Date, window: {dispatchEvent() {}}, Event: class {}, fetch: async () => ({ok:false}),
    Pulse: {copyLink: (getURL, name) => { const button = new Element('button'); button.setAttribute('aria-label', `Copy link to ${name}`); button.getURL = getURL; return button; }},
    location: { href: 'https://status.example/' + hash, hash, pathname: '/', search: '' },
    history: { replaceState: (_, __, url) => { context.lastUrl = String(url); context.location.href = String(url); }, pushState: (_, __, url) => { context.lastUrl = String(url); context.location.href = String(url); } },
    document: { addEventListener() {}, createElement: tag => new Element(tag), createTextNode: text => new Element('#text', text), getElementById: id => nodes[id] },
  });
  vm.runInContext(readFileSync(path.join(__dirname, '../../../../../core/web/technologies.js'), 'utf8'), context);
  context.PulseTech = context.window.PulseTech;
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
  assert.equal(nodes.total.textContent, '3 websites · 1 up · 1 not reporting');
});
test('search, status and hosting filters intersect and update the visible count', () => {
  const {run, nodes} = page();
  run('Object.assign(ui,{place:"host-a",filter:"unknown",query:"art"}); renderGroups()');
  assert.equal(run('visibleWebsites().map(w => w.id).join(",")'), 'path');
  assert.equal(nodes.total.textContent, '1 of 3 websites · 0 up · 1 not reporting');
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

test('dropdown omits counts and intersects networks with hosting and health', () => {
  const {run,nodes} = page();
  run('data.websites[0].network="Network"; data.websites[2].network="Network"; renderDropdowns()');
  const button = nodes.network.children.find(b => b.textContent === 'Network');
  assert.ok(button);
  assert.equal(button.value, 'Network');
  run('ui.network="Network"; renderDropdowns(); renderGroups()');
  assert.equal(nodes.network.value, 'Network');
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
test('website filter tags, search and status round-trip in shared URLs and clear together', () => {
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


test('expansion and polling retain card disclosures instead of removing focused controls', () => {
  const {run, nodes} = page();
  run('renderGroups()');
  const card = nodes.groups.children[1];
  const button = card.firstElementChild;
  run('pick("path")');
  assert.equal(nodes.groups.children[1], card);
  assert.equal(card.firstElementChild, button);
  assert.equal(button.attributes['aria-expanded'], 'true');
  run('renderGroups()');
  assert.equal(card.firstElementChild, button);
  button.events.click();
  assert.equal(button.attributes['aria-expanded'], 'false');
});

test('header actions open a site safely and copy its entry link with active filters', () => {
  const {run, nodes} = page('?network=Example');
  run('ui.network=null; ui.query="art"; renderGroups()');
  const card = nodes.groups.children[0];
  const [visit, share] = card.children[1].children;
  assert.equal(visit.href, 'https://a.example.test/Art/');
  assert.equal(visit.target, '_blank');
  assert.equal(visit.rel, 'noopener noreferrer');
  const link = new URL(share.getURL());
  assert.equal(link.searchParams.get('site'), 'path');
  assert.equal(link.searchParams.get('q'), 'art');
  assert.equal(run('ui.picked'), null);
});

test('plugins are searchable with shared scope, stale evidence and unknown vulnerability status', () => {
  const {run} = page();
  run(`data.websites[0].plugin_inventory={environments:[{name:'live',is_live:true,status:'complete',scope:'network',collected_at:'2020-01-01T00:00:00Z',plugins:[{slug:'synthetic-forms',version:'2.0',status:'active-network',is_version_vulnerable:null}]}]}; ui.query='synthetic-forms';`);
  assert.equal(run('visibleWebsites().length'),1);
  const text=run('renderPlugins(data.websites[0]).textContent');
  assert.match(text,/Stale inventory/);
  assert.match(text,/individual subsite activation has not been collected/);
  assert.match(text,/Not assessed/);
  assert.match(text,/Network active/);
});

test('details format sizes, durations, counts and dates for readers', () => {
  const {run}=page();
  assert.equal(run('fact("bandwidth_bytes_24h",134723654)'), '134.7 MB');
  assert.equal(run('fact("disk_bytes",2046342988)'), '2 GB');
  assert.equal(run('fact("response_ms",1150)'), '1.15 s');
  assert.equal(run('fact("http_4xx_24h",3590)'), '3,590');
  assert.doesNotMatch(run('fact("analytics_at","2026-11-07T17:26:29+00:00")'), /T17:|\+00:00/);
});

test('expanded cards span two columns without overlapping neighbours and clamp on narrow screens', () => {
  const {run,nodes}=page('#site=a');
  run('renderGroups(); requestAnimationFrame=fn=>{fn();return 1;}; cancelAnimationFrame=()=>{}; getComputedStyle=()=>({columnGap:"12px",getPropertyValue:()=>"320px"});');
  nodes.groups.clientWidth=1000;
  nodes.groups.children.forEach(card=>{card.getBoundingClientRect=()=>({height:100});});
  run('scheduleLayout()');
  assert.equal(nodes.groups.children[0].style.gridColumn,'1 / span 2');
  assert.equal(nodes.groups.children[1].style.gridColumn,'3 / span 1');
  assert.equal(nodes.groups.children[2].style.gridRow,'113 / span 100');
  nodes.groups.clientWidth=400;
  run('scheduleLayout()');
  assert.ok(nodes.groups.children.every(c=>c.style.gridColumn==='1 / span 1'));
});

test('collapsed cards show flagged plugin versions and deduplicate environment findings', () => {
  const {run,nodes}=page();
  run(`data.websites[0].plugin_inventory={environments:[
    {name:'production',is_live:true,plugins:[{slug:'example-payments',title:'Example Payments',version:'1.2.3',is_version_vulnerable:true},{slug:'unknown',version:'9.0',is_version_vulnerable:null}]},
    {name:'staging',is_live:false,plugins:[{slug:'example-payments',title:'Example Payments',version:'1.2.3',is_version_vulnerable:true}]}]};
    data.websites[0].alerts=[{severity:'warning',text:'A plugin or theme with a known vulnerability is installed'},{severity:'critical',text:'HTTP check failed'}]; renderGroups();`);
  const card=nodes.groups.children.find(c=>c.dataset.websiteId==='z');
  assert.match(card.textContent,/Example Payments · 1.2.3/);
  assert.match(card.textContent,/Provider flagged · Live \/ staging/);
  assert.match(card.textContent,/HTTP check failed/);
  assert.doesNotMatch(card.textContent,/known vulnerability|unknown · 9.0/);
  assert.equal((card.textContent.match(/Example Payments/g)||[]).length,1);
  assert.equal(card.firstElementChild.attributes['aria-expanded'],'false');
});

test('generic warning remains when no plugin detail is flagged', () => {
  const {run,nodes}=page();
  run(`data.websites[0].alerts=[{severity:'warning',text:'A plugin or theme with a known vulnerability is installed'}]; renderGroups();`);
  assert.match(nodes.groups.children.find(c=>c.dataset.websiteId==='z').textContent,/known vulnerability/);
});

test('shared and staging-only findings keep scope and preserve unmatched provider counts', () => {
  const {run,nodes}=page();
  run(`data.websites[2].hosting={name:'Network',facts:{plugins_vulnerable:2},plugin_inventory:{environments:[{name:'staging',is_live:false,plugins:[{slug:'example-gallery',version:'4.0',is_version_vulnerable:true}]}]}}; renderGroups();`);
  const card=nodes.groups.children.find(c=>c.dataset.websiteId==='path');
  assert.match(card.textContent,/example-gallery · 4.0/);
  assert.match(card.textContent,/Provider flagged · Shared installation · staging/);
  assert.doesNotMatch(card.textContent,/Provider flagged · Shared installation · Live/);
  assert.match(card.textContent,/Additional plugins or themes flagged; details unavailable/);
});

test('boolean plugin queries intersect or union websites with normal operator precedence', () => {
  const {run}=page();
  run(`data.websites[0].plugin_inventory={environments:[{is_live:true,plugins:[{slug:'example-search',version:'4.2'},{slug:'example-payments',version:'1.2'}]}]};
    data.websites[1].plugin_inventory={environments:[{is_live:true,plugins:[{slug:'example-search',version:'4.3'}]}]};`);
  for (const [query,ids] of [
    ['example-search AND example-payments','z'],
    ['example-search example-payments','z'],
    ['example-search OR example-payments','a,z'],
    ['example-search NOT example-payments','a'],
    ['(example-search OR art) AND NOT example-payments','a,path'],
    ['art OR example-search AND example-payments','path,z'],
    ['example-search and example-payments','z'],
    ['"a.example.test/Art"','path'],
  ]) {
    run(`ui.query=${JSON.stringify(query)}`);
    assert.equal(run('visibleWebsites().map(w=>w.id).join(",")'),ids,query);
  }
});

test('boolean deep link retains its expression and shows matching installed versions without inventing warnings', () => {
  const {run,nodes,context}=page();
  run(`data.websites[0].plugin_inventory={environments:[{name:'production',is_live:true,plugins:[
    {slug:'example-search',title:'Example Search',version:'4.2',is_version_vulnerable:false},
    {slug:'example-payments',title:'Example Payments',version:'1.2',is_version_vulnerable:true}]}]};
    ui.query='Example-Search AND Example-Payments'; writeFilters(); renderGroups();`);
  assert.equal(new URL(context.lastUrl).searchParams.get('q'),'Example-Search AND Example-Payments');
  assert.equal(page(new URL(context.lastUrl).search).run('ui.query'),'Example-Search AND Example-Payments');
  assert.equal(nodes.groups.children.length,1);
  const card=nodes.groups.children[0];
  assert.match(card.textContent,/Example Search · 4.2Installed · Live/);
  assert.match(card.textContent,/Example Payments · 1.2⚠ Provider flagged · Live/);
  assert.equal(card.firstElementChild.attributes['aria-expanded'],'false');
});

test('malformed boolean queries explain the error and never broaden results', () => {
  const {run,nodes}=page();
  for (const query of ['art AND','art OR','(art','"art','art )','AND art']) {
    run(`ui.query=${JSON.stringify(query)}; renderGroups()`);
    assert.equal(run('visibleWebsites().length'),0,query);
    assert.ok(run('searchExpression().error'),query);
    assert.match(nodes.groups.children[0].textContent,/phrase|operator|parenthes/i);
  }
});

test('patching provenance distinguishes the parent installation, account and collection source', () => {
  const {run,nodes}=page('#site=path');
  run(`data.websites[2].hosting={name:'Network',hostname:'network.example.test',facts:{account:'EXAMPLE_ACCOUNT'},plugin_inventory:{environments:[{name:'staging',is_live:false,source:'kinsta-wp-cli',scope:'network',plugins:[{slug:'example-forms',version:'3.2',is_version_vulnerable:true}]}]}}; renderGroups();`);
  const card=nodes.groups.children.find(c=>c.dataset.websiteId==='path');
  assert.match(card.firstElementChild.textContent,/WordPress plugins · Provider A · Account EXAMPLE ACCOUNT · Installation network.example.test/);
  assert.match(card.textContent,/Installed WordPress plugins/);
  assert.match(card.textContent,/Source: Kinsta WP-CLI · Shared WordPress network/);
  assert.match(card.textContent,/Provider flagged · Shared installation · staging/);
  assert.match(card.textContent,/individual subsite activation has not been collected/);
});

function networkPage() {
  const p = page();
  p.run(`data.websites = [
    {id:'root',name:'Main site',hostname:'network.example.test',url:'https://network.example.test/',group:'host-a',network:'Network',state:'degraded',facts:{php_version:'8.3',wordpress_version:'7.1'},plugin_inventory:{environments:[{name:'live',is_live:true,scope:'network',plugins:[{slug:'shared-search',version:'4.2',is_version_vulnerable:true},{slug:'shared-payments',version:'1.2'}]}]}},
    {id:'child',name:'Art',hostname:'network.example.test',url:'https://network.example.test/art/',group:'host-a',network:'Network',state:'up',hosting:{website_id:'root',name:'Network',hostname:'network.example.test',facts:{php_version:'8.3',wordpress_version:'7.1'},plugin_inventory:{environments:[{name:'live',is_live:true,scope:'network',plugins:[{slug:'shared-search',version:'4.2',is_version_vulnerable:true},{slug:'shared-payments',version:'1.2'}]}]}}},
    {id:'other',name:'Other',hostname:'other.example.test',group:'host-a',state:'up',plugin_inventory:{environments:[{name:'staging',plugins:[{slug:'shared-search',version:'4.3'}]}]}}
  ];`);
  return p;
}
test('plugin boolean searches return explicit installation patch targets with matching scope', () => {
  const {run,nodes} = networkPage();
  run('ui.query="shared-search AND shared-payments"; renderGroups()');
  assert.equal(run('visibleWebsites().map(w=>w.id).join(",")'),'root');
  assert.equal(nodes.total.textContent,'1 patching target · 2 matching websites');
  assert.match(nodes.groups.textContent,/WordPress installation/);
  assert.match(nodes.groups.textContent,/1 subsite · Patch shared files at this installation/);
  assert.match(nodes.groups.textContent,/shared-search · 4.2/);
  assert.doesNotMatch(nodes.groups.textContent,/4.3/);
  run('pick("root")');
  assert.match(nodes.groups.textContent,/WordPress subsites · 1/);
  assert.match(nodes.groups.textContent,/https:\/\/network.example.test\/art\//);
  assert.match(nodes.groups.textContent,/same environment/);
});
test('website browsing and explicit individual results retain subsite identity and parent links', () => {
  const {run,nodes} = networkPage();
  run('ui.query="art"; renderGroups(); pick("child")');
  assert.equal(run('installationView()'),false);
  assert.match(nodes.groups.textContent,/WordPress subsite/);
  assert.match(nodes.groups.textContent,/Patch parent: network.example.test/);
  assert.match(nodes.groups.textContent,/staging is patched separately/);
  run('ui.query="shared-search"; ui.view="websites"; ui.picked=null; renderGroups()');
  assert.equal(run('visibleWebsites().length'),3);
});
test('grouping preserves boolean predicates on each website instead of combining different subsites', () => {
  const {run,nodes} = networkPage();
  run('ui.query="art AND shared-payments"; renderGroups()');
  assert.equal(run('visibleWebsites().map(w=>w.id).join(",")'),'root');
  assert.equal(nodes.total.textContent,'1 patching target · 1 matching website');
  run('ui.query="art AND Main"; renderGroups()');
  assert.equal(run('visibleWebsites().length'),0);
});
test('PHP and WordPress filters group shared installations and keep unrelated installations separate', () => {
  const {run} = networkPage();
  run('ui.php="8.3"');
  assert.equal(run('visibleWebsites().map(w=>w.id).join(",")'),'root');
  run('ui.php=null; ui.query="shared-search"; data.websites[2].hostname="network.example.test"');
  assert.equal(run('visibleWebsites().map(w=>w.id).sort().join(",")'),'other,root');
});
test('explicit patching view and override round-trip in links and clear with other filters', () => {
  const {run,context} = networkPage();
  run('ui.view="installations"; ui.query="art"; writeFilters()');
  const restored=page(new URL(context.lastUrl).search);
  assert.equal(restored.run('ui.view'),'installations');
  restored.run('clearFilters();writeFilters()');
  assert.equal(new URL(restored.context.lastUrl).searchParams.has('view'),false);
});
test('missing parent records never erase a matching subsite and explicit subsite links remain reviewable', () => {
  const {run} = networkPage();
  run('ui.query="shared-search"; ui.picked="child"');
  assert.equal(run('visibleWebsites().some(w=>w.id==="child")'),true);
  run('ui.picked=null; data.websites=data.websites.filter(w=>w.id!=="root")');
  assert.equal(run('visibleWebsites().some(w=>w.id==="child")'),true);
});

test('patching targets sort by the installation address displayed on the card', () => {
  const {run}=networkPage();
  run('ui.query="shared-search"; data.websites[0].hostname="z.example.test"; data.websites[2].hostname="a.example.test"');
  assert.equal(run('visibleWebsites().map(w=>w.id).join(",")'),'other,root');
});

function advisoryPlugin(extra = {}) {
  return {slug:'example-payments',title:'Example Payments',version:'1.2.3',status:'active',update_version:'1.3',is_version_vulnerable:true,is_update_version_vulnerable:true,
    advisory_context:JSON.stringify({contract:'wordpress.plugin-security/1',source:'WPVulnerability',status:'matched',version:'1.2.3',retrieved_at:'2026-11-08T12:00:00Z',advisories:[{
      title:'Example Payments stored XSS',cves:['CVE-2026-12345'],range:{max_version:'1.2.3',max_operator:'le'},unfixed:true,fixed_version:null,
      ratings:[{version:'3.1',score:'7.1',severity:'high',vector:'CVSS:3.1/AV:N/PR:N/UI:R'}],weaknesses:[{id:'79',name:'Cross-site scripting'}],
      references:[{id:'CVE-2026-12345',name:'CVE',url:'https://www.cve.org/CVERecord?id=CVE-2026-12345'},{name:'bad',url:'javascript:alert(1)'},{name:'lookalike',url:'https://wordfence.com.evil.example/'}]
    }]}),...extra};
}
test('CVE search uses version-matched advisories and preserves parent grouping', () => {
  const {run,nodes,context}=networkPage();
  context.syntheticAdvisory=advisoryPlugin();
  run('data.websites[0].plugin_inventory.environments[0].plugins=[syntheticAdvisory];data.websites[1].hosting.plugin_inventory=data.websites[0].plugin_inventory;ui.query="CVE-2026-12345";renderGroups()');
  assert.equal(run('visibleWebsites().map(w=>w.id).join(",")'),'root');
  assert.equal(nodes.total.textContent,'1 patching target · 2 matching websites');
  assert.match(nodes.groups.textContent,/CVE-2026-12345 · high · CVSS 3.1 7.1 · WPVulnerability/);
  assert.match(nodes.groups.textContent,/No patch reported for this advisory/);
  assert.match(nodes.groups.textContent,/offered update also Kinsta-flagged/);
});
test('expanded findings show ranges, source rating conditions, activation and safe references', () => {
  const {run,context}=page(); context.syntheticAdvisory=advisoryPlugin();
  const cell=run('renderPluginSecurity(syntheticAdvisory)');
  assert.match(cell.textContent,/Affected versions: ≤ 1.2.3/);
  assert.match(cell.textContent,/Privileges: none · User interaction: required/);
  const detail=cell.children.find(c=>c.tag==='details');
  const references=detail.children.find(c=>c.className==='advisory-references').children;
  assert.equal(references.length,1);
  assert.equal(references[0].rel,'noopener noreferrer');
  assert.equal(references[0].target,'_blank');
});
test('missing or version-mismatched advisory evidence is never interpreted as safety', () => {
  const {run,context}=page(); context.syntheticAdvisory=advisoryPlugin({version:'9.0'});
  assert.equal(run('pluginSecurity(syntheticAdvisory)'),null);
  assert.match(run('renderPluginSecurity(syntheticAdvisory).textContent'),/Advisory details not collected/);
  for (const [status,label] of [['unmapped','not mapped'],['unavailable','unavailable'],['unassessed','needs review'],['no_matching_advisory','not a clean scan']]) {
    context.syntheticAdvisory=advisoryPlugin({advisory_context:JSON.stringify({contract:'wordpress.plugin-security/1',source:'WPVulnerability',status,version:'1.2.3',advisories:[]})});
    assert.match(run('renderPluginSecurity(syntheticAdvisory).textContent'),new RegExp(label));
  }
});
test('available updates and fix boundaries remain separate from provider and advisory assessments', () => {
  const {run,context}=page();context.syntheticAdvisory=advisoryPlugin({is_update_version_vulnerable:null});
  assert.match(run('updateLabel(syntheticAdvisory)'),/update security not assessed/);
  context.syntheticAdvisory=advisoryPlugin({is_update_version_vulnerable:false});
  assert.match(run('updateLabel(syntheticAdvisory)'),/Kinsta does not flag offered update/);
  assert.doesNotMatch(run('updateLabel(syntheticAdvisory)'),/safe|fixed|patched/i);
  context.syntheticAdvisory=advisoryPlugin({update_version:null});
  assert.equal(run('updateLabel(syntheticAdvisory)'),'No update version reported');
});

test('malformed nested advisory fields fail safely and never break rendering', () => {
  const {run,context}=page();
  context.syntheticAdvisory=advisoryPlugin({advisory_context:JSON.stringify({contract:'wordpress.plugin-security/1',source:'WPVulnerability',status:'matched',version:'1.2.3',advisories:[{range:{},cves:'invalid',ratings:[null,42],references:[null,'invalid'],weaknesses:{}}]})});
  assert.doesNotThrow(()=>run('renderPluginSecurity(syntheticAdvisory)'));
  assert.equal(run('pluginSecurity(syntheticAdvisory).advisories[0].ratings.length'),0);
});
