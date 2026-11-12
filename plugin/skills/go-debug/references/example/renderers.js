// Views for the types the knative/func pull-secret check moves around.
// render.py pastes this file into the page. Keep it inside the block so its
// names do not clash with the page's own.
(() => {
  const CREDS = ['Username', 'Password', 'Auth', 'IdentityToken', 'RegistryToken'];
  const q = (h, s) => `<span class="v-str">${h.esc(JSON.stringify(s))}</span>`;

  // docker/cli and go-containerregistry auth entries: which credentials are set.
  const auth = {
    leaf: true,
    full(v, h) {
      const chips = [];
      for (const n of CREDS) {
        const s = h.str(h.field(v, n));
        if (!s) continue;
        let plain = '';
        if (n === 'Auth') {
          try { const d = atob(s); if (/^[\x20-\x7e]+$/.test(d)) plain = ` <span class="v-type">(${h.esc(d)})</span>`; } catch (e) {}
        }
        chips.push(`<span class="chip good">${n}: <span class="v-str">${h.esc(s)}</span>${plain}</span>`);
      }
      if (!chips.length) chips.push('<span class="chip none">no credentials</span>');
      const sa = h.str(h.field(v, 'ServerAddress'));
      if (sa) chips.push(`<span class="chip dim">ServerAddress: ${h.esc(JSON.stringify(sa))}</span>`);
      return `<span class="chips">${chips.join('')}</span>`;
    },
    short(v, h) {
      const set = CREDS.filter(n => h.str(h.field(v, n)));
      return set.length ? `AuthConfig{${set.join(', ')} set}` : 'AuthConfig{no credentials}';
    },
  };
  RENDERERS['types.AuthConfig'] = auth;
  RENDERERS['authn.AuthConfig'] = auth;

  // Show only the auths map of a ConfigFile; the other fields stay empty here.
  RENDERERS['configfile.ConfigFile'] = {
    full(v, h, depth, prev) {
      const cs = h.str(h.field(v, 'CredentialsStore'));
      return `<span class="v-type">configfile.ConfigFile${v.ptr ? ` ${h.esc(v.ptr)}` : ''}</span><div class="fields">` +
        `<div><span class="f">AuthConfigs</span>: ${h.renderMap(h.field(v, 'AuthConfigs'), depth + 1, prev ? h.field(prev, 'AuthConfigs') : null)}</div>` +
        (cs ? `<div><span class="f">CredentialsStore</span>: ${q(h, cs)}</div>` : '') +
        '<div class="v-type">other fields hidden</div></div>';
    },
    short: (v, h) => `ConfigFile{${h.fmt1(h.field(v, 'AuthConfigs'))}}`,
  };

  RENDERERS['knative.configFileKeychain'] = {
    full: (v, h, depth) => `<span class="v-type">configFileKeychain</span><div class="fields"><div><span class="f">cf</span>: ${h.render(h.field(v, 'cf'), depth + 1)}</div></div>`,
    short: () => 'configFileKeychain',
  };

  RENDERERS['v1.Secret'] = {
    full(v, h, depth) {
      const meta = h.field(v, 'ObjectMeta');
      const data = h.field(v, 'Data');
      const rows = ((data && data.map) || []).map(([k, val]) => `<div>${q(h, h.str(k))}: ${h.render(val, depth + 2)}</div>`).join('');
      return '<span class="v-type">v1.Secret</span><div class="fields">' +
        `<div><span class="f">Name</span>: ${q(h, h.str(h.field(meta, 'Name')))}</div>` +
        `<div><span class="f">Type</span>: ${q(h, h.str(h.field(v, 'Type')))}</div>` +
        `<div><span class="f">Data</span>:${rows}</div></div>`;
    },
    short: (v, h) => `Secret ${JSON.stringify(h.str(h.field(h.field(v, 'ObjectMeta'), 'Name')))}`,
  };

  RENDERERS['v1.ServiceAccount'] = {
    full(v, h) {
      const ips = h.field(v, 'ImagePullSecrets');
      const names = ((ips && ips.list) || []).map(x => JSON.stringify(h.str(h.field(x, 'Name'))));
      return `<span class="v-type">v1.ServiceAccount</span><div class="fields"><div><span class="f">ImagePullSecrets</span>: [${h.esc(names.join(', '))}]</div></div>`;
    },
    short: () => 'ServiceAccount',
  };

  // go-containerregistry image references, as the string they stand for.
  const ref = (v, h) => {
    const t = h.shortType(v.t).replace(/^\*/, '');
    if (t === 'name.Registry') return h.str(h.field(v, 'registry')) || 'index.docker.io';
    if (t === 'name.Repository') return ref(h.field(v, 'Registry'), h) + '/' + h.str(h.field(v, 'repository'));
    if (t === 'name.Tag') return ref(h.field(v, 'Repository'), h) + ':' + h.str(h.field(v, 'tag'));
    if (t === 'name.Digest') return ref(h.field(v, 'Repository'), h) + '@' + h.str(h.field(v, 'digest'));
    return '';
  };
  for (const t of ['name.Registry', 'name.Repository', 'name.Tag', 'name.Digest']) {
    RENDERERS[t] = {
      leaf: true,
      full: (v, h) => `${q(h, ref(v, h))} <span class="v-type">${t}</span>`,
      short: (v, h) => JSON.stringify(ref(v, h)),
    };
  }
})();
