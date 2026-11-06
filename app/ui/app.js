// Forever Launcher UI. Everything privileged happens in Rust (src-tauri); this file only calls its commands.
const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const $ = (id) => document.getElementById(id);

let state = null;      // snapshot from get_state
let draft = null;      // settings being edited in the drawer
let toastTimer = 0;
let contentBusy = false;
let workshopBusy = false;
let workshopReport = null;
let layoutTimer = 0;
let layoutRequest = 0;
let contentSelection = null;
let contentState = null;

function toast(text) {
  const t = $('toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 4500);
}

function log(line) {
  const pre = $('log');
  const time = new Date().toLocaleTimeString(lang);
  pre.textContent += `[${time}] ${line}\n`;
  pre.scrollTop = pre.scrollHeight;
}

function setStep(text, kind = '') {
  const s = $('step');
  s.textContent = text;
  s.className = 'step' + (kind ? ' ' + kind : '');
}

// ------------------------------------------------------------------------------------------------ state
// '' follows the system language; Rust gets the same language for its messages
function setLanguage(setting) {
  const code = resolveLanguage(setting);
  if (code === lang && document.documentElement.lang === code) return;
  applyLanguage(code);
  invoke('set_language', { language: code });
}

async function refresh() {
  state = await invoke('get_state');
  state.settings.workshop ||= { referenceDir: '', manifestSource: '' };
  setLanguage(state.settings.language);
  $('realm-field').textContent = t('realm', { name: state.settings.server.name || 'Forever' });
  $('version').textContent = `v${state.version} · ${{ windows: 'Windows', macos: 'macOS', linux: 'Linux' }[state.platform]}`;
  $('signup').hidden = !state.settings.server.website;
  const logged = !!state.email;
  $('view-login').hidden = logged;
  $('view-play').hidden = !logged;
  $('account').hidden = !logged;
  const actualVersion = state.officialClient?.version || state.gameVersion;
  $('game-field').textContent = `WoW Forever${actualVersion ? ` ${actualVersion}` : ''}`;
  $('game-login-mode').textContent = t(state.gameAutoLogin ? 'automaticGameLogin' : 'manualGameLogin');
  if (logged) {
    $('account-email').textContent = state.email;
    $('avatar').textContent = state.email[0].toUpperCase();
  }
  updatePlayButton();
  fillWorkshop();
}

function updatePlayButton() {
  const play = $('play');
  const incompatible = state.settings.protectClientFiles && state.officialClient && !state.officialClient.ready;
  play.disabled = contentBusy || state.playing || !state.gameFound || !!incompatible;
  play.classList.toggle('running', state.playing);
  play.textContent = workshopBusy ? t('working') : state.playing ? t('inGame') : t('play');
  updateContentActions();
  updateWorkshopActions();
  if (!state.gameFound && !state.playing) setStep(t('chooseGameDir'), 'err');
  else if (incompatible && !state.playing) setStep(officialMessage(state.officialClient), 'err');
  for (const id of ['quick-download', 'quick-repair']) $(id).hidden = !!state.settings.protectClientFiles;
}

async function refreshStatus() {
  const pill = $('status');
  try {
    const s = await invoke('server_status');
    pill.dataset.state = s.online && s.login ? 'online' : s.online || s.login ? 'partial' : 'offline';
    $('status-text').textContent = t(s.online && s.login ? 'online' : s.online || s.login ? 'starting' : 'offline');
  } catch {
    pill.dataset.state = 'offline';
    $('status-text').textContent = t('unreachable');
  }
}

async function refreshChecks() {
  try {
    const c = await invoke('checks');
    showCheck('check-hosts', c.hosts, c.hostsDetail);
    showCheck('check-cert', c.certificate, c.certificateDetail);
    // on Linux the prefix certificate is installed automatically at launch: only the hosts entry needs the user
    const needsCert = state.platform !== 'linux' && !c.certificate;
    const blocking = !c.hosts || needsCert;
    $('setup-notice').hidden = !blocking;
    $('setup-detail').textContent = [!c.hosts && c.hostsDetail, needsCert && c.certificateDetail]
      .filter(Boolean).join(' · ');
    return c;
  } catch (e) {
    log(t('checks', { e }));
  }
}

function showCheck(id, ok, detail) {
  const el = $(id);
  el.dataset.ok = String(ok);
  el.querySelector('p').textContent = detail;
}

async function repair(btn) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = t('working');
  try {
    const c = await invoke('repair');
    showCheck('check-hosts', c.hosts, c.hostsDetail);
    showCheck('check-cert', c.certificate, c.certificateDetail);
    toast(c.hosts ? t('pcReady') : t('partialRepair'));
  } catch (e) {
    toast(t('failed', { e }));
  } finally {
    btn.disabled = false;
    btn.textContent = label;
    refreshChecks();
  }
}

// ------------------------------------------------------------------------------------------------ login
$('login-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const btn = $('login-btn');
  const err = $('login-error');
  err.hidden = true;
  btn.disabled = true;
  btn.textContent = t('loggingIn');
  try {
    await invoke('login', { email: $('email').value, password: $('password').value });
    $('password').value = '';
    await refresh();
    refreshChecks();
  } catch (e) {
    err.textContent = String(e);
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = t('loginButton');
  }
});

$('logout').addEventListener('click', async () => {
  await invoke('logout');
  await refresh();
});

$('signup-link').addEventListener('click', (ev) => {
  ev.preventDefault();
  window.__TAURI__.opener.openUrl(state.settings.server.website);
});

// ------------------------------------------------------------------------------------------------ play
$('play').addEventListener('click', async () => {
  log(t('launchSession'));
  state.playing = true;
  updatePlayButton();
  setStep(t('preparing'));
  try {
    await invoke('play');
  } catch (e) {
    state.playing = false;
    updatePlayButton();
    setStep(String(e), 'err');
    log(t('error', { e }));
    refresh();   // an expired session sends back to the login view
  }
});

$('setup-fix').addEventListener('click', (ev) => repair(ev.currentTarget));
$('toggle-log').addEventListener('click', (ev) => {
  ev.preventDefault();
  $('log-box').hidden = !$('log-box').hidden;
});
$('close-log').addEventListener('click', () => ($('log-box').hidden = true));
$('repair').addEventListener('click', (ev) => repair(ev.currentTarget));

listen('game', ({ payload }) => {
  const { kind, message } = payload;
  if (kind === 'log') return log(message);
  log(message);
  if (kind === 'step' || kind === 'running') setStep(message);
  if (kind === 'ready') setStep(message, 'ok');
  if (kind === 'error') setStep(message, 'err');
  if (kind === 'closed' || kind === 'error') {
    state.playing = false;
    updatePlayButton();
    if (kind === 'closed') setStep('');
  }
});

// ------------------------------------------------------------------------------------------------ settings
function option(select, value, label) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = label;
  select.append(o);
}

function fillSettings() {
  draft = structuredClone(state.settings);
  $('s-game-dir').value = draft.gameDir;
  const loc = $('s-locale');
  loc.replaceChildren();
  state.locales.forEach((l) => option(loc, l, l));
  loc.value = draft.locale;
  $('linux-settings').hidden = state.platform !== 'linux';
  if (state.platform === 'linux') {
    const r = $('s-runner');
    r.replaceChildren();
    state.runners.forEach(([name, path]) => option(r, path, name));
    if (![...r.options].some((o) => o.value === draft.linux.runner) && draft.linux.runner) option(r, draft.linux.runner, draft.linux.runner);
    r.value = draft.linux.runner;
    $('s-prefix').value = draft.linux.prefix;
    $('s-gamescope').checked = draft.linux.gamescope;
    $('s-gamescope-args').value = draft.linux.gamescopeArgs;
    $('s-keyboard').value = draft.linux.keyboard;
  }
  const language = $('s-language');
  language.replaceChildren();
  option(language, '', t('systemLanguage'));
  Object.entries(LANGUAGES).forEach(([code, name]) => option(language, code, name));
  language.value = draft.language || '';
  $('s-address').value = draft.server.address;
  $('s-website').value = draft.server.website;
  $('s-portal').value = draft.server.portal;
  $('s-bnet-port').value = draft.server.bnetPort;
  $('s-ca-file').value = draft.server.caFile || '';
  $('s-client-build').value = draft.server.clientBuild || 70658;
  $('official-result').textContent = state.officialClient ? officialDetails(state.officialClient) : '';
  $('official-connect').disabled = !!state.playing;
  gameDirState();
}

function officialMessage(report) {
  return t(report.status, { version: report.version || '—', build: report.serverBuild });
}
function officialDetails(report) {
  return [officialMessage(report), t('officialDetails', {
    version: report.version || '—', metadata: report.metadataVersion || '—',
    product: report.product || '—', build: report.serverBuild
  }), report.executable, t('officialCompleteness')].join('\n');
}
$('official-connect').addEventListener('click', async () => {
  if (state.playing || contentBusy || workshopBusy) { toast(t('wErr_running')); return; }
  const button = $('official-connect'); button.disabled = true;
  try {
    const selectedPath = $('s-game-dir').value.trim();
    const selectedBuild = Number($('s-client-build').value);
    const report = await invoke('inspect_official_client', { gameDir: selectedPath, serverBuild: selectedBuild });
    if (selectedPath !== $('s-game-dir').value.trim() || selectedBuild !== Number($('s-client-build').value)) return;
    $('official-result').textContent = officialDetails(report);
    if (!report.ready) return;
    const settings = settingsFromForm();
    settings.gameDir = report.gameDir;
    settings.protectClientFiles = true;
    settings.server.clientBuild = Number($('s-client-build').value);
    settings.locale = $('s-locale').value;
    settings.language = $('s-language').value;
    await invoke('save_settings', { settings });
    await refresh();
    draft = structuredClone(state.settings);
    $('s-game-dir').value = report.gameDir;
    gameDirState();
    toast(t('officialConnected'));
    $('official-result').textContent = officialDetails(report) + '\n' + t('officialConnected');
  } catch (e) {
    $('official-result').textContent = String(e);
  } finally { button.disabled = !!state.playing; }
});

function gameDirState() {
  const el = $('game-dir-state');
  const dir = $('s-game-dir').value.trim();
  const same = dir === state.settings.gameDir;
  const game = state.platform === 'macos' ? t('gameApp') : state.gameExecutable || 'Wow.exe / WowB.exe';
  el.textContent = !dir ? t('noFolder') : same && state.gameFound ? t('gameFound', { game }) : same ? t('gameMissing', { game }) : '';
  el.className = 'small ' + (same && state.gameFound ? 'ok' : dir && same ? 'ko' : '');
}

function openSettings() {
  fillSettings();
  $('settings').hidden = false;
  $('scrim').hidden = false;
  refreshChecks();
}

function closeSettings() {
  $('settings').hidden = true;
  $('scrim').hidden = true;
}

function updateContentActions() {
  const busy = contentBusy || !!state?.playing;
  const gameDir = $('s-game-dir').value.trim();
  $('content-choose').disabled = busy || !gameDir;
  $('content-install').disabled = busy || !!state?.settings.protectClientFiles || !contentSelection?.preview.ready || contentSelection.gameDir !== gameDir;
  $('content-rollback').disabled = busy || !!state?.settings.protectClientFiles || !contentState?.installed;
}
function resetContent() {
  contentSelection = null; contentState = null;
  $('content-preview').textContent = '';
  $('content-installed').textContent = '';
  $('content-backup').textContent = '';
  updateContentActions();
}
function showContentStatus(status) {
  contentState = status;
  $('content-installed').textContent = status.recoveryNeeded ? t('contentRecovery') : status.installed ? t('contentInstalled', { name: status.installed }) : t('contentNone');
  $('content-backup').textContent = status.backup ? t('contentBackup', { path: status.backup }) : '';
  updateContentActions();
}
async function refreshContent() {
  const gameDir = $('s-game-dir').value.trim();
  try {
    const catalog = await invoke('content_catalog');
    $('content-catalog').textContent = catalog.filter(p => p.status === 'experimental').map(p => t('contentExperimental', { name: p.name })).join(' · ');
    if (gameDir) {
      const status = await invoke('content_status', { gameDir });
      if ($('s-game-dir').value.trim() === gameDir) showContentStatus(status);
    }
  } catch (e) { $('content-installed').textContent = String(e); }
  updateContentActions();
}
function contentWorking(value) {
  contentBusy = value;
  $('s-game-dir').disabled = value; $('pick-game').disabled = value;
  $('save-settings').disabled = value;
  updateContentActions(); updatePlayButton();
}
$('content-choose').addEventListener('click', async () => {
  try {
    const packageDir = await window.__TAURI__.dialog.open({ directory: true, title: t('contentChoose') });
    if (!packageDir) return;
    const gameDir = $('s-game-dir').value.trim();
    contentWorking(true); $('content-preview').textContent = t('working');
    const preview = await invoke('inspect_content', { gameDir, packageDir });
    contentSelection = { gameDir, packageDir, preview };
    const reasons = { unverified: 'contentUnverified', server: 'contentServer', client: 'contentClient', changed: 'contentChanged' };
    $('content-preview').textContent = preview.ready ? t('contentReady', preview) : `${preview.name} ${preview.version}: ${t(reasons[preview.reason] || 'contentUnverified')}`;
  } catch (e) { contentSelection = null; $('content-preview').textContent = String(e); }
  finally { contentWorking(false); }
});
$('content-install').addEventListener('click', async () => {
  if (state?.settings.protectClientFiles) { toast(t('official_protected')); return; }
  if (!contentSelection?.preview.ready || contentSelection.gameDir !== $('s-game-dir').value.trim()) return;
  const selected = contentSelection;
  contentWorking(true);
  try {
    showContentStatus(await invoke('install_content', { gameDir: selected.gameDir, packageDir: selected.packageDir }));
    contentSelection = null; $('content-preview').textContent = t('contentSuccess'); toast(t('contentSuccess'));
  } catch (e) { toast(String(e)); await refreshContent(); }
  finally { contentWorking(false); await refresh(); }
});
$('content-rollback').addEventListener('click', async () => {
  if (state?.settings.protectClientFiles) { toast(t('official_protected')); return; }
  contentWorking(true);
  try {
    showContentStatus(await invoke('rollback_content', { gameDir: $('s-game-dir').value.trim() }));
    contentSelection = null; $('content-preview').textContent = t('contentRestored'); toast(t('contentRestored'));
  } catch (e) { toast(String(e)); await refreshContent(); }
  finally { contentWorking(false); await refresh(); }
});
$('s-game-dir').addEventListener('input', () => { resetContent(); });
$('s-game-dir').addEventListener('change', refreshContent);

async function pick(input, title) {
  const dir = await window.__TAURI__.dialog.open({ directory: true, title, defaultPath: input.value || undefined });
  if (dir) {
    input.value = dir;
    if (input.id === 's-game-dir') {
      resetContent(); refreshContent();
      const loc = await invoke('detect_locale', { gameDir: dir });
      if (loc) $('s-locale').value = loc;
    }
  }
}

$('open-settings').addEventListener('click', () => { openSettings(); resetContent(); refreshContent(); });
$('play-settings').addEventListener('click', () => { openSettings(); resetContent(); refreshContent(); });
$('close-settings').addEventListener('click', closeSettings);
$('cancel-settings').addEventListener('click', closeSettings);
$('scrim').addEventListener('click', closeSettings);
$('pick-game').addEventListener('click', () => pick($('s-game-dir'), t('pickGameDir')));
$('pick-prefix').addEventListener('click', () => pick($('s-prefix'), t('pickPrefix')));
$('pick-ca').addEventListener('click', async () => {
  const file = await window.__TAURI__.dialog.open({ directory: false, multiple: false, title: t('caFile'),
    filters: [{ name: t('caFile'), extensions: ['crt', 'pem'] }] });
  if (file) $('s-ca-file').value = file;
});
$('s-game-dir').addEventListener('input', gameDirState);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('settings').hidden) closeSettings(); });

function settingsFromForm() {
  const settings = structuredClone(draft || state.settings);
  settings.gameDir = $('s-game-dir').value.trim();
  settings.locale = $('s-locale').value;
  settings.language = $('s-language').value;
  if (state.platform === 'linux') {
    settings.linux.runner = $('s-runner').value;
    settings.linux.prefix = $('s-prefix').value.trim();
    settings.linux.gamescope = $('s-gamescope').checked;
    settings.linux.gamescopeArgs = $('s-gamescope-args').value.trim();
    settings.linux.keyboard = $('s-keyboard').value.trim();
  }
  settings.server.address = $('s-address').value.trim();
  settings.server.website = $('s-website').value.trim();
  settings.server.portal = $('s-portal').value.trim();
  settings.server.bnetPort = Number($('s-bnet-port').value);
  settings.server.caFile = $('s-ca-file').value.trim();
  settings.server.clientBuild = Number($('s-client-build').value);
  settings.workshop = workshopSource();
  return settings;
}

$('save-settings').addEventListener('click', async () => {
  draft = settingsFromForm();
  try {
    await invoke('save_settings', { settings: draft });
    closeSettings();
    await refresh();
    refreshStatus();
    refreshChecks();
    refreshNews();
    toast(t('saved'));
  } catch (e) {
    toast(t('saveFailed', { e }));
  }
});

// ------------------------------------------------------------------------------------------------ news
// shown until the website has a blog (<website>/api/news)
const defaultNews = () => [1, 2, 3].map((i) => ({ tag: t(`news${i}Tag`), title: t(`news${i}`), image: '', url: '' }));

function openLink(url) {
  if (url) window.__TAURI__.opener.openUrl(url);
}

async function refreshNews() {
  let items = [];
  try {
    items = await invoke('news');
  } catch (e) {
    console.debug('news:', e);
  }
  const fromSite = items.length > 0;
  if (!fromSite) items = defaultNews();
  const website = state.settings.server.website;
  $('news-more').hidden = !fromSite || !website;
  $('news-more').onclick = (ev) => { ev.preventDefault(); openLink(website); };
  $('news').replaceChildren(...items.slice(0, 3).map((n) => {
    const card = document.createElement('button');
    card.className = 'news-card';
    card.type = 'button';
    // a drawn placeholder when the post has no image (or it does not load)
    const thumb = () => Object.assign(document.createElement('div'), { className: 'thumb', textContent: 'FM' });
    let img = thumb();
    if (n.image) {
      img = document.createElement('img');
      img.src = n.image;
      img.alt = '';
      img.onerror = () => img.replaceWith(thumb());
    }
    const body = document.createElement('div');
    body.className = 'body';
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = n.tag || t('newsTag');
    const title = document.createElement('strong');
    title.textContent = n.title;
    body.append(tag, title);
    if (n.date) {
      const date = document.createElement('span');
      date.className = 'date';
      date.textContent = n.date;
      body.append(date);
    }
    card.append(img, body);
    card.addEventListener('click', () => openLink(n.url || website));
    return card;
  }));
}

// ------------------------------------------------------------------------------------------------ client workshop
function page(name) {
  $('home-page').hidden = name !== 'home';
  $('workshop-page').hidden = name !== 'workshop';
  $('nav-home').classList.toggle('selected', name === 'home');
  $('nav-workshop').classList.toggle('selected', name === 'workshop');
  $('page-name').textContent = t(name === 'home' ? 'wHome' : 'wLibrary');
  updateWorkshopActions();
}
function workshopSource() {
  return { referenceDir: $('w-reference').value.trim(), manifestSource: $('w-manifest').value.trim() };
}
function fillWorkshop() {
  if (workshopBusy) return;
  $('w-target').value = state.settings.gameDir || '';
  $('w-reference').value = state.settings.workshop?.referenceDir || '';
  $('w-manifest').value = state.settings.workshop?.manifestSource || '';
  sourceState();
}
function sourceState() {
  const s = workshopSource();
  const kind = s.manifestSource ? 'wSourceManifest' : s.referenceDir ? 'wSourceReference' : 'wSourceNone';
  $('w-source-state').textContent = t(kind);
  $('w-source-state').dataset.ready = String(!!(s.manifestSource || s.referenceDir));
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(refreshWorkshopLayout, 200);
}
async function refreshWorkshopLayout() {
  const ticket = ++layoutRequest;
  const gameDir = $('w-target').value.trim(), referenceDir = $('w-reference').value.trim();
  if (!gameDir) { $('w-layout').textContent = ''; return; }
  try {
    const value = await invoke('inspect_client_locations', { gameDir, referenceDir });
    if (!value || ticket !== layoutRequest || gameDir !== $('w-target').value.trim() || referenceDir !== $('w-reference').value.trim()) return;
    $('w-layout').textContent = [t('wResolvedTarget', { path: value.targetRoot }), value.referenceRoot ? t('wResolvedSource', { path: value.referenceRoot }) : '', t('wLayoutHint')].filter(Boolean).join('\n');
  } catch {
    if (ticket === layoutRequest) $('w-layout').textContent = t('wLayoutPending');
  }
}
function updateWorkshopActions() {
  const busy = workshopBusy || contentBusy || !!state?.playing;
  for (const id of ['w-download','w-verify','w-repair','w-recover']) $(id).disabled = busy;
  for (const id of ['w-download','w-repair','w-recover']) {
    $(id).hidden = !!state?.settings.protectClientFiles;
    if (state?.settings.protectClientFiles) $(id).disabled = true;
  }
  $('w-blocked').hidden = !(state?.playing || (contentBusy && !workshopBusy));
  $('w-blocked').textContent = t(state?.playing ? 'wErr_running' : 'wErr_busy');
}
function bytes(n) {
  if (!n) return '0 B';
  const unit = Math.min(4, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** unit).toFixed(unit ? 1 : 0)} ${['B', 'KiB', 'MiB', 'GiB', 'TiB'][unit]}`;
}
function workshopWorking(value) {
  workshopBusy = value;
  contentWorking(value);
  for (const id of ['w-target','w-reference','w-manifest','w-pick-target','w-pick-reference','w-pick-manifest','w-download','w-verify','w-repair','w-recover']) $(id).disabled = value;
  $('w-cancel').disabled = !value;
  $('w-status-panel').dataset.busy = String(value);
}
async function runWorkshop(action) {
  if (state?.settings.protectClientFiles && action !== 'verify') {
    toast(t('official_protected')); return;
  }
  page('workshop');
  if (workshopBusy || contentBusy) { toast(t('wErr_busy')); return; }
  if (state.playing) { toast(t('wErr_running')); return; }
  const source = workshopSource();
  if (action !== 'recover' && !source.manifestSource && !source.referenceDir) {
    $('w-status-title').textContent = t('wChooseSource');
    $('w-status').textContent = t('wSourceNone');
    $('w-reference').focus?.(); return;
  }
  if (!$('w-target').value.trim()) { $('w-status').textContent = t('wErr_folder'); $('w-target').focus?.(); return; }
  const gameDir = $('w-target').value.trim();
  workshopWorking(true);
  $('w-report').hidden = true; $('w-copy-report').hidden = true; $('w-recover').hidden = true;
  $('w-status-panel').dataset.error = 'false';
  $('w-status-title').textContent = t('wPreparing');
  $('w-status').textContent = t('wPreparingHint');
  $('w-progress').removeAttribute?.('value');
  try {
    const report = await invoke('client_work', { request: { action, gameDir, source } });
    workshopReport = report;
    const extras = report.extraStorageFiles?.length || 0;
    const storageOnly = report.storageDifferent > 0 && report.resourceDifferent === 0;
    $('w-status-title').textContent = t(report.action === 'recover' ? 'wRecovered' : report.repaired > 0 ? 'wRestoredTitle' : extras ? 'wCascTitle' : report.different ? (storageOnly ? 'wStorageOnly' : 'wDifferences') : 'wMatches');
    $('w-status').textContent = t(report.repaired > 0 ? 'wRepairResult' : 'wVerifyResult', { checked: report.files, different: report.different, restored: report.repaired, remaining: report.remaining ?? Math.max(0, report.different - report.repaired), resources: report.resourceDifferent ?? report.different, storage: report.storageDifferent || 0 });
    if (extras) $('w-status').textContent += ' ' + t(report.quarantined > 0 ? 'wCascQuarantined' : 'wCascExtras', { count: report.quarantined || extras });
    else if (report.storageDifferent > 0) $('w-status').textContent += ' ' + t('wStorageHint');
    $('w-progress').value = 100;
    $('w-count').textContent = `${report.verified} / ${report.files}`;
    $('w-speed').textContent = bytes(report.bytes);
    $('w-current').textContent = report.profile.version ? `${report.profile.product} · ${report.profile.version}` : '';
    const lines = [report.targetRoot ? t('wResolvedTarget', { path: report.targetRoot }) : '', report.referenceRoot ? t('wResolvedSource', { path: report.referenceRoot }) : '', t(report.sourceKind === 'reference' ? 'wScopeReference' : 'wScopeManifest'), report.backup ? t('wBackup', { path: report.backup }) : '', ...(report.differences || [])];
    $('w-report-text').textContent = lines.filter(Boolean).join('\n');
    $('w-report').hidden = false; $('w-copy-report').hidden = false;
    log(t('wReportSaved', { path: report.reportPath }));
    const settings = structuredClone(state.settings); settings.workshop = source;
    if (action !== 'verify' && action !== 'recover') settings.gameDir = gameDir;
    await invoke('save_settings', { settings });
  } catch (e) {
    const code = e && typeof e === 'object' ? e.code : '';
    const message = code && TEXTS.en[`wErr_${code}`] ? t(`wErr_${code}`) : String(e?.detail || e);
    $('w-status-title').textContent = t(code === 'cancelled' ? 'wPaused' : 'wStopped');
    $('w-status').textContent = message;
    $('w-status-panel').dataset.error = String(code !== 'cancelled');
    $('w-recover').hidden = code !== 'recovery';
    if (e?.detail && code !== 'cancelled') { $('w-current').textContent = e.detail; }
    log(message);
    if (code === 'cancelled') $('w-download').querySelector('[data-i18n]').textContent = t('wResume');
  } finally {
    workshopWorking(false);
    const target = $('w-target').value, reference = $('w-reference').value, manifest = $('w-manifest').value;
    await refresh();
    // An unsaved source must survive a failed/paused operation so Resume uses the same staging files.
    $('w-target').value = target; $('w-reference').value = reference; $('w-manifest').value = manifest;
    sourceState();
  }
}
listen('client-progress', ({ payload: p }) => {
  const key = { scan: 'wPhaseScan', reference: 'wPhaseReference', verify: 'wPhaseVerify', copy: 'wPhaseCopy', download: 'wPhaseDownload', commit: 'wPhaseCommit', done: 'wComplete' }[p.phase];
  $('w-status-title').textContent = t(key || 'wPreparing');
  $('w-status').textContent = t(p.phase === 'commit' ? 'wCommitting' : p.phase === 'scan' ? 'wScanning' : p.phase === 'reference' ? 'wReadingReference' : 'wComparing');
  $('w-current').textContent = p.path || '';
  $('w-count').textContent = `${p.filesDone} / ${p.filesTotal}`;
  $('w-speed').textContent = p.bytesPerSecond ? `${bytes(p.bytesPerSecond)} / s` : '';
  if (p.bytesTotal) $('w-progress').value = Math.min(100, p.bytesDone / p.bytesTotal * 100);
  else if (p.filesTotal) $('w-progress').value = p.filesDone / p.filesTotal * 100;
  else $('w-progress').removeAttribute?.('value');
  $('w-cancel').disabled = !workshopBusy || p.phase === 'commit' || p.phase === 'done';
});
$('nav-home').addEventListener('click', () => page('home'));
$('brand-home').addEventListener('click', e => { e.preventDefault(); page('home'); });
$('nav-workshop').addEventListener('click', () => page('workshop'));
$('nav-downloads').addEventListener('click', () => page('workshop'));
$('nav-journal').addEventListener('click', () => { $('log-box').hidden = !$('log-box').hidden; });
for (const [id, action] of [['quick-download','download'],['quick-verify','verify'],['quick-repair','repair'],['w-download','download'],['w-verify','verify'],['w-repair','repair'],['w-recover','recover']]) $(id).addEventListener('click', () => runWorkshop(action));
for (const name of ['target','reference','manifest']) {
  $(`w-${name}`).addEventListener('input', sourceState);
  $(`w-pick-${name}`).addEventListener('click', async () => {
    const value = await window.__TAURI__.dialog.open({ directory: name !== 'manifest', multiple: false, title: t(name === 'target' ? 'wTarget' : name === 'reference' ? 'wReference' : 'wManifest'), ...(name === 'manifest' ? { filters: [{ name: 'JSON', extensions: ['json'] }] } : {}) });
    if (value) $(`w-${name}`).value = value;
    sourceState();
  });
}
$('w-cancel').addEventListener('click', async () => { await invoke('cancel_client_work'); $('w-cancel').disabled = true; $('w-status').textContent = t('wPausing'); });
$('w-copy-report').addEventListener('click', async () => {
  if (!workshopReport) return;
  try { await navigator.clipboard.writeText(workshopReport.reportPath); toast(t('wCopied')); }
  catch { $('w-current').textContent = workshopReport.reportPath; }
});

// ------------------------------------------------------------------------------------------------ background
function rotateBackground() {
  const slides = [...document.querySelectorAll('.backdrop .bg')];
  if (!slides.length) return;
  let current = Math.floor(Math.random() * slides.length);
  slides[current].classList.add('on');
  setInterval(() => {
    slides[current].classList.remove('on');
    current = (current + 1) % slides.length;
    slides[current].classList.add('on');
  }, 20000);
}

// ------------------------------------------------------------------------------------------------ start
rotateBackground();
(async () => {
  await refresh();
  refreshStatus();
  refreshNews();
  if (state.email) refreshChecks();
  setInterval(refreshStatus, 20000);
})();
