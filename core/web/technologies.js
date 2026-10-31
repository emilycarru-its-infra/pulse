// Locally bundled vendor artwork. Deployment-specific marks arrive through the theme.
(() => {
  const registry = {
    amplify: ['amplify', '#d96619'], aws: ['amazonwebservices', '#c66a00'], azure: ['azure', '#0078d4'], proxmox: ['proxmox', '#c65f00'],
    hyperv: ['hyperv', '#0078d4'], windows: ['windows11', '#0078d4'], linux: ['linux', '#a57700'], macos: ['apple', '#666666'],
    ubuntu: ['ubuntu', '#d74613'], debian: ['debian', '#a80030'], rocky: ['rockylinux', '#008361'],
    amazonlinux: ['amazonwebservices', '#c66a00'], apache: ['apache', '#b82043'], java: ['java', '#c94715'],
    mysql: ['mysql', '#00618a'], mariadb: ['mariadb', '#007080'], nginx: ['nginx', '#00843d'],
    nodejs: ['nodejs', '#438b35'], openssh: ['ssh', '#526780'], php: ['php', '#656aa3'],
    postgresql: ['postgresql', '#336791'], python: ['python', '#3674a5'], sqlserver: ['microsoftsqlserver', '#c52c28'],
    docker: ['docker', '#167cc1'], containerd: ['containerd', '#575757'], wordpress: ['wordpress', '#21759b'],
    kinsta: ['kinsta', '#e84f00'], greengeeks: ['greengeeks', '#387329'], powershell: ['powershell', '#245da8'],
    dotnet: ['dotnetcore', '#623697'], redis: ['redis', '#b52424'], bind: ['bind', '#325d89'],
  };
  const rules = [
    [/kinsta/i, 'kinsta'], [/green\s?geeks/i, 'greengeeks'], [/amplify/i, 'amplify'],
    [/amazon\s+linux/i, 'amazonlinux'], [/\baws\b|amazon web/i, 'aws'], [/azure/i, 'azure'],
    [/proxmox/i, 'proxmox'], [/ubuntu/i, 'ubuntu'], [/debian/i, 'debian'], [/rocky/i, 'rocky'],
    [/hyper[ -]?v/i, 'hyperv'], [/windows/i, 'windows'], [/mac\s?os|darwin|\bapple\b/i, 'macos'], [/linux/i, 'linux'],
    [/apache/i, 'apache'], [/containerd/i, 'containerd'], [/docker/i, 'docker'], [/\bjava\b/i, 'java'],
    [/mariadb/i, 'mariadb'], [/mysql/i, 'mysql'], [/nginx/i, 'nginx'], [/node\.?js/i, 'nodejs'],
    [/openssh/i, 'openssh'], [/\bphp\b/i, 'php'], [/postgres/i, 'postgresql'], [/python/i, 'python'],
    [/sql server/i, 'sqlserver'], [/wordpress|^wp\b/i, 'wordpress'], [/powershell/i, 'powershell'],
    [/\.net/i, 'dotnet'], [/redis/i, 'redis'], [/\bbind\b/i, 'bind'],
  ];
  const overrides = new Map();
  const pickers = new Map();
  function brand(label, hint = '') {
    const value = String(label || '');
    if (overrides.has(value.toLowerCase())) return overrides.get(value.toLowerCase());
    if (/mysql\s*\/\s*mariadb/i.test(hint || value)) return {key:'mysql', color:'#00618a', icons:['/core/brands/mysql.svg', '/core/brands/mariadb.svg']};
    const key = rules.find(([pattern]) => pattern.test(hint || value))?.[1];
    if (!key) return null;
    const [file, color] = registry[key];
    return {key, color, icon: `/core/brands/${file.includes('.') ? file : `${file}.svg`}`};
  }
  function badge(label, hint = '', kind = 'label') {
    const node = document.createElement('span'); node.className = kind === 'binary' ? 'tech-badge tech-binary' : 'tech-badge';
    const found = brand(label, hint);
    if (found) {
      node.dataset.brand = found.key || 'site'; node.style.setProperty('--tech-color', found.color);
      for (const source of found.icons || [found.icon]) {
      const icon = document.createElement('img'); icon.className = 'tech-logo'; icon.src = source;
      icon.alt = ''; icon.width = 20; icon.height = 20; icon.setAttribute('aria-hidden', 'true');
      icon.addEventListener('error', () => icon.remove(), {once: true}); node.append(icon);
      }
    }
    const text = document.createElement('span'); text.className = 'tech-label'; text.textContent = label;
    node.append(text); return node;
  }
  function picker(select, hint = '') {
    if (pickers.has(select)) return pickers.get(select).refresh();
    const wrap = document.createElement('span'); wrap.className = 'tech-picker';
    const trigger = document.createElement('button'); trigger.type = 'button'; trigger.className = 'tech-picker-trigger';
    trigger.setAttribute('role', 'combobox'); trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    const name = select.closest('label')?.querySelector('.visually-hidden')?.textContent || select.id;
    const list = document.createElement('span'); list.className = 'tech-options'; list.id = `${select.id}-options`;
    list.hidden = true; list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', name);
    trigger.setAttribute('aria-controls', list.id);
    select.after(wrap); wrap.append(trigger, list); select.hidden = true;
    select.closest('label')?.classList.add('has-tech-picker');
    let signature = '', buttons = [], search = '', lastKey = 0;
    const close = (focus = false) => { list.hidden = true; trigger.setAttribute('aria-expanded', 'false'); if (focus) trigger.focus(); };
    const focus = i => buttons[(i + buttons.length) % buttons.length]?.focus();
    const position = () => {
      list.style.left = '0'; list.style.top = 'calc(100% + 5px)'; list.style.bottom = 'auto';
      const anchor = trigger.getBoundingClientRect();
      const below = window.innerHeight - anchor.bottom - 16, above = anchor.top - 16;
      const upwards = below < 160 && above > below;
      if (upwards) { list.style.top = 'auto'; list.style.bottom = 'calc(100% + 5px)'; }
      list.style.maxHeight = `${Math.max(80, Math.min(380, window.innerHeight * .6, upwards ? above : below))}px`;
      const bounds = list.getBoundingClientRect();
      list.style.left = `${Math.max(12 - bounds.left, Math.min(0, window.innerWidth - 12 - bounds.right))}px`;
    };
    const open = () => {
      for (const [other, p] of pickers) if (other !== select) p.close();
      list.hidden = false; trigger.setAttribute('aria-expanded', 'true'); position();
      focus(Math.max(0, buttons.findIndex(b => b.dataset.value === select.value)));
    };
    function keys(event, index) {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); }
      else if (event.key === 'Tab') close();
      else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        if (list.hidden) open();
        else focus(event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : index + (event.key === 'ArrowUp' ? -1 : 1));
      } else if (event.key.length === 1 && event.key !== ' ' && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault(); if (list.hidden) open();
        search = Date.now() - lastKey > 700 ? event.key : search + event.key; lastKey = Date.now();
        const candidates = [...buttons.slice(index + 1), ...buttons.slice(0, index + 1)];
        candidates.find(b => b.textContent.toLowerCase().startsWith(search.toLowerCase()))?.focus();
      }
    }
    trigger.addEventListener('click', () => list.hidden ? open() : close());
    trigger.addEventListener('keydown', e => keys(e, Math.max(0, buttons.findIndex(b => b.dataset.value === select.value))));
    const refresh = () => {
      const options = [...select.options].sort((a, b) => {
        const rank = o => !o.value ? -1 : /^other\b/i.test(o.textContent.trim()) ? 2 : /^unknown\b|\bnot (recorded|reported)\b|\bunrecorded\b/i.test(o.textContent.trim()) ? 1 : 0;
        return rank(a) - rank(b);
      });
      const next = JSON.stringify(options.map(o => [o.value, o.textContent, o.disabled]));
      if (signature !== next) {
        const focusedValue = buttons.find(b => b === document.activeElement)?.dataset.value;
        signature = next;
        buttons = options.map((option, index) => {
          const b = document.createElement('button'); b.type = 'button'; b.tabIndex = -1;
          b.setAttribute('role', 'option'); b.dataset.value = option.value; b.disabled = option.disabled;
          b.append(badge(option.textContent, hint));
          b.addEventListener('click', () => { select.value = option.value; close(true); select.dispatchEvent(new Event('change', {bubbles: true})); refresh(); });
          b.addEventListener('keydown', e => keys(e, index)); return b;
        });
        list.replaceChildren(...buttons);
        if (!list.hidden && focusedValue !== undefined) (buttons.find(b => b.dataset.value === focusedValue) || buttons[0])?.focus();
      }
      const selected = options.find(o => o.value === select.value) || options[0];
      trigger.replaceChildren(badge(selected?.textContent || '', hint));
      trigger.setAttribute('aria-label', `${name}: ${selected?.textContent || ''}`);
      buttons.forEach(b => b.setAttribute('aria-selected', String(b.dataset.value === select.value)));
    };
    pickers.set(select, {refresh, close}); refresh();
  }
  document.addEventListener('pointerdown', e => { for (const [s, p] of pickers) if (!s.parentElement.contains(e.target)) p.close(); });
  window.PulseTech = {badge, brand, picker, refresh: () => {for (const p of pickers.values()) p.refresh();}};
  window.PulseTech.ready = fetch('/theme/technologies.json').then(r => r.ok ? r.json() : {}).then(config => {
    for (const [label, item] of Object.entries(config)) {
      if (typeof item.icon === 'string' && /^\/theme\/[\w./-]+\.(svg|png|gif)$/.test(item.icon) && /^#[\da-f]{6}$/i.test(item.color)) overrides.set(label.toLowerCase(), item);
    }
  }).catch(() => {}).then(() => window.dispatchEvent(new Event('technology-brands-ready')));
})();
