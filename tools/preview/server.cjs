const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {make} = require('./fixtures.cjs');
const root = path.resolve(__dirname, '../..');
const args = process.argv.slice(2);
const option = name => args[args.indexOf(name) + 1];
if (!args.includes('--theme')) throw new Error('Usage: node tools/preview/server.cjs --theme <theme-directory> [--port 8766]');
const theme = path.resolve(option('--theme'));
const port = args.includes('--port') ? Number(option('--port')) : 8766;
if (!Number.isInteger(port) || port < 1 || port > 65535 || !fs.statSync(theme).isDirectory()) throw new Error('Invalid preview port or theme directory');
const types = {'.svg':'image/svg+xml','.png':'image/png','.css':'text/css','.js':'text/javascript','.json':'application/json','.html':'text/html','.woff2':'font/woff2'};
http.createServer((req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/') { res.writeHead(302, {Location:'/servers/'}); res.end(); return; }
  if (/^\/(servers|websites)\/api\/status$/.test(url.pathname)) {
    const data = make(); res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify(url.pathname.startsWith('/servers/') ? data.servers : data.websites)); return;
  }
  if (['/nav.json','/hub/products.json','/access.json'].includes(url.pathname)) {
    res.setHeader('Content-Type', 'application/json'); res.end('[]'); return;
  }
  let base, relative;
  if (url.pathname.startsWith('/theme/')) {base=theme; relative=url.pathname.slice(7);}
  else if (url.pathname.startsWith('/core/')) {base=path.join(root,'core/web'); relative=url.pathname.slice(6);}
  else {
    const [,product,...parts] = url.pathname.split('/');
    if (!['servers','websites'].includes(product)) {res.writeHead(404);res.end('Not found');return;}
    base=path.join(root,'products',product,'web');relative=parts.join('/') || 'index.html';
  }
  const file=path.resolve(base,relative);
  if (!file.startsWith(base+path.sep)) {res.writeHead(404);res.end('Not found');return;}
  try {
    let body=fs.readFileSync(file);
    if (path.extname(file)==='.html') body=body.toString().replace('Mockup with sample data.','Local preview with sample data.').replace('The servers and services are real names; every status, metric and alert on this page is simulated.','Every server, status, metric and patch assessment here is simulated.');
    res.setHeader('Content-Type',types[path.extname(file)] || 'application/octet-stream');res.end(body);
  } catch {res.writeHead(404);res.end('Not found');}
}).listen(port,'127.0.0.1',()=>process.stdout.write(`Preview: http://localhost:${port}/servers/ and /websites/\n`));
