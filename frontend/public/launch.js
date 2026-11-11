/*
 * Printbuddy phone launcher.
 *
 * The installed app (manifest start_url) starts here. It tries the access
 * addresses configured under Settings -> Network in their configured order
 * (e.g. LAN first, then Tailscale) and opens the first one that answers:
 *   - this page's own address  -> normal navigation, no iframe
 *   - any other address        -> embedded in a full-screen iframe, so the
 *                                 home-screen app does not fall back to a
 *                                 Safari view with a URL bar
 *
 * The service worker keeps a copy of this page, so it also starts when the
 * address the app was installed from is unreachable (e.g. LAN IP while away).
 *
 * The address list comes from the app itself: it stores the list in this
 * origin's localStorage (when running here) or posts it to this page (when
 * embedded). Nothing is fetched without login.
 *
 * Keep the protocol in sync with frontend/src/utils/launcher.ts.
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'pb-launcher-addresses';
  var PROBE_TIMEOUT_MS = 2500;
  var MAX_ADDRESSES = 10;

  var de = /^de\b/i.test(navigator.language || '');
  var T = de
    ? {
        connecting: 'Verbinde …',
        via: 'Verbinde über {name} …',
        none: 'Keine Adresse erreichbar.',
        pick: 'Trotzdem öffnen:',
        retry: 'Erneut versuchen',
        insecure: 'nicht einbettbar (HTTP von HTTPS)',
      }
    : {
        connecting: 'Connecting …',
        via: 'Connecting via {name} …',
        none: 'No address is reachable.',
        pick: 'Open anyway:',
        retry: 'Try again',
        insecure: 'cannot be embedded (HTTP from HTTPS)',
      };

  var statusEl = document.getElementById('status');
  var messageEl = document.getElementById('message');
  var listEl = document.getElementById('list');
  var retryEl = document.getElementById('retry');
  var frame = document.getElementById('frame');
  var insetsEl = document.getElementById('insets');
  var own = window.location.origin;
  var frameOrigin = null;
  var currentPath = '/';

  function normalizeOrigin(value) {
    try {
      var u = new URL(String(value));
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
      return u.origin;
    } catch (e) {
      return null;
    }
  }

  function sanitizeAddresses(list) {
    if (!Array.isArray(list)) return [];
    var out = [];
    var seen = {};
    for (var i = 0; i < list.length && out.length < MAX_ADDRESSES; i++) {
      var item = list[i];
      if (!item || typeof item !== 'object') continue;
      var origin = normalizeOrigin(item.url);
      if (!origin || seen[origin]) continue;
      seen[origin] = true;
      var name = String(item.name || '').trim().slice(0, 50) || origin;
      out.push({ name: name, url: origin });
    }
    return out;
  }

  function loadAddresses() {
    try {
      return sanitizeAddresses(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
    } catch (e) {
      return [];
    }
  }

  function saveAddresses(list) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitizeAddresses(list)));
    } catch (e) {
      /* storage unavailable - the list is simply not remembered */
    }
  }

  // Only same-site paths: "/queue?x=1", never "//evil.example" or "https:..."
  function safePath(value) {
    if (typeof value !== 'string' || value.charAt(0) !== '/' || value.charAt(1) === '/' || value.charAt(1) === '\\') {
      return '/';
    }
    return value;
  }

  function readInsets() {
    var cs = window.getComputedStyle(insetsEl);
    return {
      top: parseFloat(cs.paddingTop) || 0,
      right: parseFloat(cs.paddingRight) || 0,
      bottom: parseFloat(cs.paddingBottom) || 0,
      left: parseFloat(cs.paddingLeft) || 0,
    };
  }

  function embedUrl(origin, path) {
    var u = new URL(safePath(path), origin);
    var i = readInsets();
    u.searchParams.set('pb_embed', '1');
    u.searchParams.set('pb_insets', [i.top, i.right, i.bottom, i.left].map(Math.round).join(','));
    return u.toString();
  }

  function postInsets() {
    if (!frameOrigin || !frame.contentWindow) return;
    frame.contentWindow.postMessage({ source: 'pb-launcher', type: 'insets', insets: readInsets() }, frameOrigin);
  }

  function canEmbed(origin) {
    // An https page may not embed an http page (mixed content).
    return !(window.location.protocol === 'https:' && origin.indexOf('http:') === 0);
  }

  function probe(origin) {
    if (!canEmbed(origin) && origin !== own) return Promise.resolve('insecure');
    return new Promise(function (resolve) {
      var img = new Image();
      var done = false;
      function finish(result) {
        if (done) return;
        done = true;
        window.clearTimeout(timer);
        img.onload = img.onerror = null;
        resolve(result);
      }
      var timer = window.setTimeout(function () {
        img.src = '';
        finish('fail');
      }, PROBE_TIMEOUT_MS);
      img.onload = function () { finish('ok'); };
      img.onerror = function () { finish('fail'); };
      // __pb_probe makes the service worker step aside, so a cached copy
      // never pretends an unreachable address is reachable.
      img.src = origin + '/img/favicon-16x16.png?__pb_probe=' + Date.now();
    });
  }

  function open(origin, path) {
    if (origin === own) {
      window.location.replace(safePath(path));
      return;
    }
    frameOrigin = origin;
    currentPath = safePath(path);
    frame.src = embedUrl(origin, currentPath);
    frame.hidden = false;
    statusEl.hidden = true;
  }

  function renderList(addresses, states, clickable) {
    while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
    addresses.forEach(function (a) {
      var li = document.createElement('li');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.disabled = !clickable;
      var state = states[a.url] || 'checking';
      var dot = document.createElement('span');
      dot.className = 'dot ' + (state === 'ok' ? 'ok' : state === 'checking' ? 'checking' : 'fail');
      var name = document.createElement('span');
      name.className = 'name';
      name.textContent = a.name;
      var url = document.createElement('span');
      url.className = 'url';
      url.textContent = state === 'insecure' ? T.insecure : a.url.replace(/^https?:\/\//, '');
      name.appendChild(url);
      btn.appendChild(dot);
      btn.appendChild(name);
      btn.addEventListener('click', function () { open(a.url, currentPath); });
      li.appendChild(btn);
      listEl.appendChild(li);
    });
  }

  function start(params) {
    var addresses = loadAddresses();
    currentPath = safePath(params.get('path') || '/');

    // Nothing configured, or this address is not one of them: plain app start.
    var ownListed = addresses.some(function (a) { return a.url === own; });
    if (!addresses.length || !ownListed) {
      window.location.replace(currentPath);
      return;
    }

    // Explicit switch requested by the app (connection menu).
    var to = normalizeOrigin(params.get('to'));
    if (to && addresses.some(function (a) { return a.url === to; })) {
      open(to, currentPath);
      return;
    }

    statusEl.hidden = false;
    frame.hidden = true;
    retryEl.hidden = true;
    messageEl.textContent = T.connecting;
    var states = {};
    renderList(addresses, states, false);

    // Probe all at once, decide strictly in the configured order.
    var probes = addresses.map(function (a) {
      return probe(a.url).then(function (result) {
        states[a.url] = result;
        renderList(addresses, states, false);
        return result;
      });
    });

    (function pick(i) {
      if (i >= addresses.length) {
        messageEl.textContent = T.none + ' ' + T.pick;
        renderList(addresses, states, true);
        retryEl.hidden = false;
        return;
      }
      probes[i].then(function (result) {
        if (result === 'ok') {
          messageEl.textContent = T.via.replace('{name}', addresses[i].name);
          open(addresses[i].url, currentPath);
        } else {
          pick(i + 1);
        }
      });
    })(0);
  }

  // Messages from the embedded app
  window.addEventListener('message', function (event) {
    if (!frameOrigin || event.origin !== frameOrigin || event.source !== frame.contentWindow) return;
    var data = event.data;
    if (!data || data.source !== 'pb-app') return;
    if (data.type === 'ready') {
      postInsets();
    } else if (data.type === 'addresses') {
      var list = sanitizeAddresses(data.addresses);
      if (list.length) saveAddresses(list);
    } else if (data.type === 'switch') {
      var target = normalizeOrigin(data.url);
      if (target && loadAddresses().some(function (a) { return a.url === target; })) {
        open(target, data.path);
      }
    }
  });

  frame.addEventListener('load', postInsets);
  window.addEventListener('resize', postInsets);
  window.addEventListener('orientationchange', function () { window.setTimeout(postInsets, 300); });

  retryEl.textContent = T.retry;
  retryEl.addEventListener('click', function () { start(new URLSearchParams()); });

  start(new URLSearchParams(window.location.search));
})();
