/* Printbuddy device dashboard for the slicer "Device" tab (#52).
 *
 * Served from /api/v1/vp-host/<vp id>. All data calls send the virtual
 * printer's API key: OrcaSlicer injects it into every fetch() as X-API-Key;
 * otherwise it comes from ?apikey= in the URL or from the key form.
 */
(function () {
  'use strict';

  var BASE = document.body.getAttribute('data-base') || '';
  var VP_ID = (BASE.match(/\/vp-host\/(\d+)/) || [])[1] || '0';
  var POLL_MS = 2000;
  var KEY_STORE = 'pb-device-key-' + VP_ID;

  var STRINGS = {
    en: {
      printer: 'Printer', openPrintbuddy: 'Open in Printbuddy', authTitle: 'API key required',
      authHelp: "Enter the virtual printer's API key from Printbuddy (Settings → Virtual printers). It is stored in this browser only.",
      apiKey: 'API key', save: 'Save', remaining: 'Remaining', eta: 'Done at', stop: 'Stop', confirmStop: 'Really stop?',
      pause: 'Pause', resume: 'Resume', material: 'Active material', camera: 'Webcam', snapshot: 'Snapshot',
      fullscreen: 'Fullscreen', temperatures: 'Temperatures', nozzle: 'Nozzle', bed: 'Bed', chamber: 'Chamber',
      setTemps: 'Set', preheatPla: 'Preheat PLA', cooldown: 'Cool down', control: 'Control', light: 'Chamber light',
      footer: 'Printbuddy device view · refreshes every 2 s', updatedJustNow: 'Updated just now',
      updatedAgo: 'Updated {s} s ago', noTarget: 'This virtual printer has no target printer yet. In Printbuddy open Settings → Virtual printers, pick the target printer for “{name}” and the dashboard shows it here.',
      noJob: 'No active print', layer: 'Layer {a} / {b}', noCamera: 'No camera is configured for this printer in Printbuddy.',
      cameraOffline: 'Camera stream not available. Retrying…', cameraConnecting: 'Connecting to camera…', offline: 'Offline', connectionLost: 'Printbuddy is not reachable. Retrying…',
      wrongKey: 'The API key was rejected. Enter the key of this virtual printer.', done: 'Command sent',
      fan_part: 'Part cooling fan', fan_aux: 'Auxiliary fan', fan_chamber: 'Chamber fan', target: 'Target',
      state_RUNNING: 'Printing', state_PAUSE: 'Paused', state_PREPARE: 'Preparing', state_SLICING: 'Preparing',
      state_FINISH: 'Finished', state_FAILED: 'Failed', state_IDLE: 'Ready', state_OFFLINE: 'Offline', state_UNKNOWN: 'Unknown',
      viaVp: 'via virtual printer “{name}”'
    },
    de: {
      printer: 'Drucker', openPrintbuddy: 'In Printbuddy öffnen', authTitle: 'API-Key erforderlich',
      authHelp: 'Gib den API-Key des virtuellen Druckers aus Printbuddy ein (Einstellungen → Virtuelle Drucker). Er wird nur in diesem Browser gespeichert.',
      apiKey: 'API-Key', save: 'Speichern', remaining: 'Verbleibend', eta: 'Fertig um', stop: 'Abbrechen', confirmStop: 'Wirklich abbrechen?',
      pause: 'Pausieren', resume: 'Fortsetzen', material: 'Aktives Material', camera: 'Webcam', snapshot: 'Schnappschuss',
      fullscreen: 'Vollbild', temperatures: 'Temperaturen', nozzle: 'Düse', bed: 'Bett', chamber: 'Kammer',
      setTemps: 'Setzen', preheatPla: 'PLA vorheizen', cooldown: 'Abkühlen', control: 'Steuerung', light: 'Innenbeleuchtung',
      footer: 'Printbuddy Device-Ansicht · aktualisiert sich alle 2 s', updatedJustNow: 'Gerade aktualisiert',
      updatedAgo: 'Aktualisiert vor {s} s', noTarget: 'Für diesen virtuellen Drucker ist noch kein Zieldrucker gewählt. Wähle in Printbuddy unter Einstellungen → Virtuelle Drucker den Zieldrucker für „{name}“, dann erscheint er hier.',
      noJob: 'Kein aktiver Druck', layer: 'Schicht {a} / {b}', noCamera: 'Für diesen Drucker ist in Printbuddy keine Kamera eingerichtet.',
      cameraOffline: 'Kamerastream nicht verfügbar. Neuer Versuch…', cameraConnecting: 'Kamera wird verbunden…', offline: 'Offline', connectionLost: 'Printbuddy ist nicht erreichbar. Neuer Versuch…',
      wrongKey: 'Der API-Key wurde abgelehnt. Gib den Key dieses virtuellen Druckers ein.', done: 'Befehl gesendet',
      fan_part: 'Bauteillüfter', fan_aux: 'Zusatzlüfter', fan_chamber: 'Gehäuselüfter', target: 'Ziel',
      state_RUNNING: 'Druckt', state_PAUSE: 'Pausiert', state_PREPARE: 'Vorbereitung', state_SLICING: 'Vorbereitung',
      state_FINISH: 'Fertig', state_FAILED: 'Fehlgeschlagen', state_IDLE: 'Bereit', state_OFFLINE: 'Offline', state_UNKNOWN: 'Unbekannt',
      viaVp: 'über virtuellen Drucker „{name}“'
    }
  };
  var LANG = /^de\b/i.test(navigator.language || '') ? 'de' : 'en';
  document.documentElement.lang = LANG;

  function t(key, vars) {
    var text = (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.en[key] || key;
    if (vars) {
      Object.keys(vars).forEach(function (name) { text = text.replace('{' + name + '}', vars[name]); });
    }
    return text;
  }

  function $(id) { return document.getElementById(id); }

  function storageGet(store, key) {
    try { return window[store].getItem(key); } catch (e) { return null; }
  }
  function storageSet(store, key, value) {
    try {
      if (value === null) window[store].removeItem(key); else window[store].setItem(key, value);
    } catch (e) { /* storage blocked: keep working without it */ }
  }

  // ---- API key -----------------------------------------------------------
  var params = new URLSearchParams(window.location.search);
  var apiKey = params.get('apikey') || params.get('api_key') || storageGet('localStorage', KEY_STORE) || '';
  if (params.get('apikey')) storageSet('localStorage', KEY_STORE, apiKey);

  function api(path, options) {
    options = options || {};
    var headers = { 'Accept': 'application/json' };
    // Same header name OrcaSlicer injects, so the two never end up doubled.
    if (apiKey) headers['X-API-Key'] = apiKey;
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(BASE + '/device/api/' + path, {
      method: options.method || 'GET',
      headers: headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      cache: 'no-store',
      credentials: 'same-origin'
    }).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (!response.ok) {
          var err = new Error((data && (data.error || data.detail)) || ('HTTP ' + response.status));
          err.status = response.status;
          throw err;
        }
        return data;
      });
    });
  }

  // ---- static labels -----------------------------------------------------
  Array.prototype.forEach.call(document.querySelectorAll('[data-i18n]'), function (el) {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-i18n-label]'), function (el) {
    el.setAttribute('aria-label', t(el.getAttribute('data-i18n-label')));
  });

  // ---- state -------------------------------------------------------------
  var lastUpdate = 0;
  var pollTimer = null;
  var current = null;
  var cameraToken = null;
  var cameraTokenAt = 0;
  var cameraPrinter = null;
  var cameraRetry = null;
  var stopArmed = null;
  var busy = false;

  function showMessage(text, isError) {
    var el = $('message');
    if (!text) { el.hidden = true; return; }
    el.textContent = text;
    el.className = 'banner' + (isError ? ' err' : '');
    el.hidden = false;
  }

  function stateTone(state, connected) {
    if (!connected) return 'err';
    if (state === 'RUNNING' || state === 'PREPARE' || state === 'SLICING' || state === 'IDLE' || state === 'FINISH') return 'ok';
    if (state === 'PAUSE') return 'warn';
    if (state === 'FAILED') return 'err';
    return '';
  }

  function stateLabel(state, connected) {
    if (!connected) return t('state_OFFLINE');
    return t('state_' + (state || 'UNKNOWN'));
  }

  function formatMinutes(minutes) {
    if (minutes === null || minutes === undefined || minutes < 0) return '–';
    var h = Math.floor(minutes / 60);
    var m = Math.round(minutes % 60);
    return h + ':' + (m < 10 ? '0' : '') + m + ' h';
  }

  function formatEta(minutes) {
    if (!minutes || minutes <= 0) return '–';
    var done = new Date(Date.now() + minutes * 60000);
    return done.toLocaleTimeString(LANG === 'de' ? 'de-DE' : undefined, { hour: '2-digit', minute: '2-digit' });
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  // ---- rendering ---------------------------------------------------------
  function renderHeader(data) {
    var p = data.printer;
    $('printer-name').textContent = p ? p.name : data.vp.name;
    $('vp-name').textContent = p ? t('viaVp', { name: data.vp.name }) : '';
  }

  function renderJob(p) {
    var tone = stateTone(p.state, p.connected);
    var pill = $('state-pill');
    pill.textContent = stateLabel(p.state, p.connected);
    pill.className = 'pill' + (tone ? ' ' + tone : '');
    $('state-dot').className = 'dot' + (tone ? ' ' + tone : '');
    $('state-title').textContent = stateLabel(p.state, p.connected);

    $('job-file').textContent = p.file || t('noJob');
    $('job-model').textContent = [p.model, p.ip_address].filter(Boolean).join(' · ');

    var thumb = $('thumb');
    var img = thumb.querySelector('img');
    if (p.cover_path && cameraToken) {
      var src = p.cover_path + '?token=' + encodeURIComponent(cameraToken) + '&f=' + encodeURIComponent(p.file || '');
      if (!img) {
        img = el('img');
        img.alt = '';
        img.onerror = function () { img.remove(); };
        thumb.appendChild(img);
      }
      if (img.getAttribute('src') !== src) img.setAttribute('src', src);
    } else if (img) {
      img.remove();
    }

    var progress = typeof p.progress === 'number' ? Math.max(0, Math.min(100, p.progress)) : null;
    $('progress-block').hidden = !p.is_active_job && progress === null;
    $('progress-value').textContent = progress === null ? '–' : Math.round(progress) + ' %';
    $('progress-fill').style.width = (progress || 0) + '%';
    $('progress-bar').setAttribute('aria-valuenow', String(Math.round(progress || 0)));
    $('layer').textContent = p.layer && p.total_layers ? t('layer', { a: p.layer, b: p.total_layers }) : '';
    var remaining = p.is_active_job ? p.remaining_minutes : null;
    $('remaining').textContent = formatMinutes(remaining);
    $('eta').textContent = formatEta(remaining);

    var pause = $('btn-pause');
    var paused = p.state === 'PAUSE';
    pause.textContent = paused ? t('resume') : t('pause');
    pause.disabled = !p.connected || !p.is_active_job || busy;
    $('btn-stop').disabled = !p.connected || !p.is_active_job || busy;
    if (!stopArmed) $('btn-stop').textContent = t('stop');

    var errors = $('errors');
    errors.innerHTML = '';
    (p.errors || []).forEach(function (err) { errors.appendChild(el('li', null, 'HMS ' + err.code)); });
    errors.hidden = !(p.errors && p.errors.length);
  }

  function renderMaterials(p) {
    var box = $('materials');
    box.innerHTML = '';
    (p.materials || []).forEach(function (slot) {
      var item = el('div', 'slot' + (slot.active ? ' active' : ''));
      var swatch = el('span', 'swatch');
      if (slot.color) swatch.style.background = slot.color;
      item.appendChild(swatch);
      item.appendChild(el('span', 'slot-label', slot.label));
      item.appendChild(el('span', 'slot-type', slot.type || '–'));
      box.appendChild(item);
    });
    $('material-card').hidden = !(p.materials && p.materials.length);
  }

  function heaterLabel(row) {
    var base = t(row.kind);
    if (row.kind === 'nozzle' && row.index !== null && row.index !== undefined) return base + ' T' + row.index;
    return base;
  }

  function renderTemps(p) {
    var box = $('temps');
    box.innerHTML = '';
    (p.temperatures || []).forEach(function (row) {
      var wrap = el('div', 'stack-sm');
      var head = el('div', 'temp-row-head');
      head.appendChild(el('b', null, heaterLabel(row)));
      var value = el('span');
      value.appendChild(el('b', null, Math.round(row.current) + '°'));
      value.appendChild(el('span', 'muted', ' / ' + Math.round(row.target || 0) + '°'));
      head.appendChild(value);
      var bar = el('div', 'bar thin');
      var fill = el('div', 'bar-fill ' + (row.target > 0 ? 'heat' : 'idle'));
      fill.style.width = Math.max(2, Math.min(100, (row.current / (row.kind === 'bed' ? 120 : row.kind === 'chamber' ? 70 : 300)) * 100)) + '%';
      bar.appendChild(fill);
      wrap.appendChild(head);
      wrap.appendChild(bar);
      box.appendChild(wrap);
    });
    var disabled = !p.connected || busy;
    ['t-nozzle', 't-bed', 'btn-preheat', 'btn-cooldown'].forEach(function (id) { $(id).disabled = disabled; });
    $('temp-form').querySelector('button').disabled = disabled;
  }

  function renderControls(p) {
    var box = $('fans');
    var active = document.activeElement;
    if (!(active && active.type === 'range' && box.contains(active))) {
      box.innerHTML = '';
      ['part', 'aux', 'chamber'].forEach(function (fan) {
        var speed = p.fans ? p.fans[fan] : null;
        if (speed === null || speed === undefined) return;
        var wrap = el('div', 'stack-sm');
        var head = el('div', 'range-head');
        var label = el('label', null, t('fan_' + fan));
        label.htmlFor = 'fan-' + fan;
        var value = el('b', null, speed + ' %');
        head.appendChild(label);
        head.appendChild(value);
        var input = el('input');
        input.type = 'range'; input.min = '0'; input.max = '100'; input.step = '5';
        input.id = 'fan-' + fan; input.value = String(speed); input.disabled = !p.connected;
        input.addEventListener('input', function () { value.textContent = input.value + ' %'; });
        input.addEventListener('change', function () {
          act('fan', { fan: fan, speed: Number(input.value) });
        });
        wrap.appendChild(head);
        wrap.appendChild(input);
        box.appendChild(wrap);
      });
    }
    var light = $('light');
    var showLight = !!(p.light && p.light.supported && p.connected);
    $('light-row').hidden = !showLight;
    $('control-card').hidden = !showLight && !box.children.length;
    if (document.activeElement !== light) light.checked = !!(p.light && p.light.on);
  }

  function renderCamera(p) {
    var img = $('camera-img');
    var empty = $('camera-empty');
    var live = $('camera-live');
    var snap = $('btn-snapshot');
    if (!p.camera || !p.camera.available) {
      if (cameraPrinter !== null) { img.removeAttribute('src'); cameraPrinter = null; }
      img.hidden = true; live.hidden = true; snap.hidden = true;
      empty.hidden = false;
      empty.textContent = p.connected ? t('noCamera') : t('state_OFFLINE');
      return;
    }
    if (!cameraToken) return;
    snap.hidden = false;
    snap.href = p.camera.snapshot_path + '?token=' + encodeURIComponent(cameraToken);
    if (cameraPrinter !== p.id) {
      cameraPrinter = p.id;
      startStream(p);
    }
  }

  function startStream(p) {
    var img = $('camera-img');
    var empty = $('camera-empty');
    clearTimeout(cameraRetry);
    img.hidden = true;
    $('camera-live').hidden = true;
    empty.hidden = false;
    empty.textContent = t('cameraConnecting');
    img.onload = function () { img.hidden = false; empty.hidden = true; $('camera-live').hidden = false; };
    img.onerror = function () {
      img.hidden = true; $('camera-live').hidden = true;
      empty.hidden = false; empty.textContent = t('cameraOffline');
      cameraRetry = setTimeout(function () {
        if (cameraPrinter === p.id) startStream(p);
      }, 5000);
    };
    img.src = p.camera.stream_path + '?fps=10&token=' + encodeURIComponent(cameraToken) + '&t=' + Date.now();
  }

  function render(data) {
    current = data;
    $('auth-panel').hidden = true;
    renderHeader(data);
    var p = data.printer;
    if (!p) {
      $('dashboard').hidden = true;
      $('state-pill').hidden = true;
      showMessage(t('noTarget', { name: data.vp.name }));
      return;
    }
    $('state-pill').hidden = false;
    showMessage('');
    $('dashboard').hidden = false;
    renderJob(p);
    renderMaterials(p);
    renderTemps(p);
    renderControls(p);
    renderCamera(p);
    document.title = p.name + ' – Printbuddy';
  }

  function tickUpdated() {
    if (!lastUpdate) { $('updated').textContent = ''; return; }
    var seconds = Math.round((Date.now() - lastUpdate) / 1000);
    $('updated').textContent = seconds < 2 ? t('updatedJustNow') : t('updatedAgo', { s: seconds });
  }

  // ---- data flow ---------------------------------------------------------
  function ensureCameraToken() {
    // Stream tokens live 60 min; renew after 50 and restart the stream.
    if (cameraToken && Date.now() - cameraTokenAt < 50 * 60000) return Promise.resolve();
    return api('camera-token', { method: 'POST' }).then(function (data) {
      var renewed = !!cameraToken;
      cameraToken = data.token;
      cameraTokenAt = Date.now();
      if (renewed) cameraPrinter = null;
    });
  }

  function needKey(message) {
    clearTimeout(pollTimer);
    $('dashboard').hidden = true;
    $('auth-panel').hidden = false;
    showMessage(message, true);
  }

  function poll() {
    clearTimeout(pollTimer);
    ensureCameraToken()
      .then(function () { return api('state'); })
      .then(function (data) {
        lastUpdate = Date.now();
        render(data);
        pollTimer = setTimeout(poll, POLL_MS);
      })
      .catch(function (err) {
        if (err.status === 401) { needKey(t('wrongKey')); return; }
        showMessage(err.status ? err.message : t('connectionLost'), true);
        pollTimer = setTimeout(poll, POLL_MS * 2);
      });
  }

  function act(action, body) {
    if (!current || !current.printer) return Promise.resolve();
    busy = true;
    return api('control/' + action, { method: 'POST', body: body || {} })
      .then(function () { showMessage(''); })
      .catch(function (err) { showMessage(err.message, true); })
      .then(function () { busy = false; poll(); });
  }

  // ---- events ------------------------------------------------------------
  $('btn-pause').addEventListener('click', function () {
    if (!current || !current.printer) return;
    act(current.printer.state === 'PAUSE' ? 'resume' : 'pause');
  });

  $('btn-stop').addEventListener('click', function () {
    var button = $('btn-stop');
    if (!stopArmed) {
      button.textContent = t('confirmStop');
      stopArmed = setTimeout(function () { stopArmed = null; button.textContent = t('stop'); }, 4000);
      return;
    }
    clearTimeout(stopArmed);
    stopArmed = null;
    button.textContent = t('stop');
    act('stop');
  });

  $('temp-form').addEventListener('submit', function (event) {
    event.preventDefault();
    var nozzle = $('t-nozzle').value;
    var bed = $('t-bed').value;
    var chain = Promise.resolve();
    if (nozzle !== '') chain = chain.then(function () { return act('temperature', { heater: 'nozzle', target: Number(nozzle) }); });
    if (bed !== '') chain = chain.then(function () { return act('temperature', { heater: 'bed', target: Number(bed) }); });
    chain.then(function () { $('t-nozzle').value = ''; $('t-bed').value = ''; });
  });

  $('btn-preheat').addEventListener('click', function () {
    act('temperature', { heater: 'nozzle', target: 200 }).then(function () {
      return act('temperature', { heater: 'bed', target: 60 });
    });
  });

  $('btn-cooldown').addEventListener('click', function () { act('cooldown'); });

  $('light').addEventListener('change', function (event) { act('light', { on: event.target.checked }); });

  $('btn-fullscreen').addEventListener('click', function () {
    var box = $('camera');
    if (document.fullscreenElement) { document.exitFullscreen(); return; }
    if (box.requestFullscreen) box.requestFullscreen().catch(function () { /* not allowed in this web view */ });
  });

  $('auth-form').addEventListener('submit', function (event) {
    event.preventDefault();
    apiKey = $('auth-key').value.trim();
    storageSet('localStorage', KEY_STORE, apiKey || null);
    $('auth-key').value = '';
    cameraToken = null;
    showMessage('');
    poll();
  });

  setInterval(tickUpdated, 1000);
  poll();
})();
