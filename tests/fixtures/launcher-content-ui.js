const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = process.argv[2];
const elements = new Map();
function element() {
  return { value:'', textContent:'', hidden:false, disabled:false, dataset:{}, handlers:{}, children:[],
    classList:{add(){},remove(){},toggle(){}}, addEventListener(n,fn){const before=this.handlers[n];this.handlers[n]=before?async e=>{await before(e);await fn(e);}:fn;},
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},
    querySelector(){return element();},setAttribute(){}, get options(){return this.children;} };
}
function get(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);}
let selected={id:'legion-dalaran',name:'Dalaran',version:'1',ready:false,reason:'unverified',files:0};
const calls=[];
let workshopReply="match";
let officialReply={gameDir:'E:/Battle.net/World of Warcraft/_forever_',executable:'E:/Battle.net/World of Warcraft/_forever_/Wow.exe',product:'wowf',version:'1.60.1.70790',metadataVersion:'1.60.1.70658',serverBuild:70658,ready:false,status:'official_mismatch'};
const state={settings:{gameDir:'E:/client/_classic_beta_',language:'en',locale:'ruRU',server:{website:'',name:'Forever'}},gameFound:true,gameVersion:'1.60.1.70532',email:null,platform:'windows',version:'test',locales:['ruRU'],runners:[],playing:false};
async function invoke(cmd,args){
  calls.push({cmd,args});
  if(cmd==='get_state')return structuredClone(state);
  if(cmd==='inspect_official_client')return structuredClone(officialReply);
  if(cmd==='server_status')return {online:true,login:true};
  if(cmd==='news')return [];
  if(cmd==='checks')return {hosts:true,certificate:true};
  if(cmd==='content_catalog')return [{name:'Dalaran',status:'experimental'}];
  if(cmd==='content_status')return {installed:null,recoveryNeeded:false,backup:null};
  if(cmd==='inspect_content')return selected;
  if(cmd==='install_content')return {installed:'Owned zone 1',recoveryNeeded:false,backup:'E:/backup'};
  if(cmd==='rollback_content')return {installed:null,recoveryNeeded:false,backup:null};
  if(cmd==='inspect_client_locations')return {targetRoot:'E:/copy',targetData:'E:/copy/Data',referenceRoot:'E:/original',referenceData:'E:/original/Data'};
  if(cmd==='native_client_work')return {complete:true,build:70658,gameDir:'E:/managed/_forever_',reportPath:'E:/reports/native.json',checked:20000};
  if(cmd==='client_work') {
    if(args.request.source.manifestSource==='bad.json')throw {code:'manifest',detail:'unsupported format'};
    if(workshopReply==='extras' || workshopReply==='quarantined')return {action:workshopReply==='extras'?'verify':'repair',sourceKind:'reference',profile:{product:'wowf',version:'1.60.1.70658'},files:1661,verified:1661,different:18,resourceDifferent:0,storageDifferent:18,remaining:workshopReply==='extras'?18:0,repaired:workshopReply==='extras'?0:18,quarantined:workshopReply==='extras'?0:18,extraStorageFiles:Array.from({length:18},(_,i)=>`Data/data/extra-${i}.idx`),bytes:400,differences:['Data/data/RepairMarker.psv'],reportPath:'E:/reports/client.json',backup:workshopReply==='extras'?null:'E:/copy/.forever-multi/operations/test'};
    if(workshopReply==='storage')return {action:'verify',sourceKind:'reference',profile:{product:'wowf',version:'1.60.1.70658'},files:1661,verified:1574,different:87,resourceDifferent:0,storageDifferent:87,remaining:87,repaired:0,bytes:400,differences:['Data/data/shmem'],reportPath:'E:/reports/client.json'};
    if(workshopReply==='restored')return {action:'repair',sourceKind:'reference',profile:{product:'wowf',version:'1.60.1.70658'},files:1661,verified:1661,different:92,resourceDifferent:4,storageDifferent:88,remaining:0,repaired:92,bytes:400,differences:['Data/data/shmem'],reportPath:'E:/reports/client.json'};
    return {action:args.request.action,sourceKind:'reference',profile:{product:'wowf',version:'1.60.1.70658'},files:4,verified:4,different:0,repaired:0,bytes:400,differences:[],reportPath:'E:/reports/client.json'};
  }
  if(cmd==='save_settings'){Object.assign(state.settings,args.settings);if(args.settings.protectClientFiles)state.officialClient=structuredClone(officialReply);return;}

}
const context=vm.createContext({console,structuredClone,Date,Math,navigator:{languages:['en']},
  setTimeout(){return 1;},clearTimeout(){},setInterval(){},
  document:{getElementById:get,querySelectorAll(s){return s==='.backdrop .bg'?[element()]:[];},createElement:element,addEventListener(){},documentElement:{lang:'en'}},
  window:{__TAURI__:{core:{invoke},event:{listen(){}},dialog:{async open(){return 'E:/package';}},opener:{openUrl(){}}}}});
vm.runInContext(fs.readFileSync(path.join(root,'app/ui/i18n.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(root,'app/ui/app.js'),'utf8'),context);
(async()=>{
  await new Promise(resolve=>setImmediate(resolve));
  vm.runInContext('openSettings(); resetContent();',context);
  await vm.runInContext('refreshContent()',context);
  assert.match(get('content-catalog').textContent,/experimental/);
  await get('content-choose').handlers.click();
  assert.equal(get('content-install').disabled,true);
  assert.match(get('content-preview').textContent,/not been confirmed/);
  selected={id:'owned',name:'Owned zone',version:'1',ready:true,reason:'',files:2};
  await get('content-choose').handlers.click();
  assert.equal(get('content-install').disabled,false);
  await get('content-install').handlers.click();
  const install=calls.find(c=>c.cmd==='install_content');
  assert.equal(install.args.gameDir,'E:/client/_classic_beta_');
  assert.equal(install.args.packageDir,'E:/package');
  assert.equal(get('content-install').disabled,true);
  assert.equal(get('content-rollback').disabled,false);
  await get('content-rollback').handlers.click();
  assert.equal(get('content-rollback').disabled,true);
  await get('content-choose').handlers.click();
  get('s-game-dir').value='E:/other/_classic_beta_';
  await get('s-game-dir').handlers.input();
  assert.equal(get('content-install').disabled,true);
  vm.runInContext('state.playing=true;updateContentActions()',context);
  assert.equal(get('content-choose').disabled,true);
  // Every locale contains a real translation for each content label.
  vm.runInContext(`for(const key of Object.keys(TEXTS.en).filter(k=>k.startsWith('content')))for(const locale of Object.keys(TEXTS))if(!TEXTS[locale][key])throw Error(locale+':'+key)`,context);
  vm.runInContext('state.playing=false;page("workshop");',context);
  get('w-target').value='E:/copy/_forever_';get('w-reference').value='';get('w-manifest').value='';
  const before=calls.filter(c=>c.cmd==='client_work').length;
  await get('w-verify').handlers.click();
  assert.equal(calls.filter(c=>c.cmd==='client_work').length,before,'unconfigured source must not pretend to verify');
  assert.match(get('w-status').textContent,/Choose your original/);
  get('w-reference').value='E:/original';
  await get('w-verify').handlers.click();
  const work=calls.find(c=>c.cmd==='client_work');
  assert.equal(work.args.request.gameDir,'E:/copy/_forever_');assert.equal(work.args.request.source.referenceDir,'E:/original');
  assert.equal(get('w-status-title').textContent,'Files match the selected copy.');assert.equal(get('w-copy-report').hidden,false);assert.equal(get('w-progress').value,100);
  await vm.runInContext('refreshWorkshopLayout()',context);
  assert.match(get('w-layout').textContent,/E:\/copy/);assert.match(get('w-layout').textContent,/E:\/original/);
  workshopReply='storage';await get('w-verify').handlers.click();
  assert.equal(get('w-status-title').textContent,'Differences from the selected copy were found.');assert.match(get('w-status').textContent,/resource differences: 0/);
  workshopReply='restored';await get('w-repair').handlers.click();
  assert.equal(get('w-status-title').textContent,'Files restored.');assert.match(get('w-status').textContent,/92 restored · 0 unresolved/);
  workshopReply='extras';await get('w-verify').handlers.click();
  assert.equal(get('w-status-title').textContent,'Differences from the selected copy were found.');assert.match(get('w-status').textContent,/differences do not establish corruption/);assert.doesNotMatch(get('w-status').textContent,/Recovery will|reconciliation|moved into/);
  workshopReply='quarantined';await get('w-repair').handlers.click();
  assert.equal(get('w-status-title').textContent,'Files restored.');assert.match(get('w-status').textContent,/18 restored · 0 unresolved/);assert.match(get('w-status').textContent,/moved into the backup: 18/);
  vm.runInContext('state.playing=true;updatePlayButton()',context);
  assert.equal(get('w-repair').disabled,true);assert.equal(get('w-blocked').hidden,false);
  const countBefore=calls.filter(c=>c.cmd==='client_work').length;await get('quick-repair').handlers.click();assert.equal(calls.filter(c=>c.cmd==='client_work').length,countBefore);
  vm.runInContext('state.playing=false;updatePlayButton()',context);
  workshopReply='match';
  get('w-manifest').value='bad.json';
  await get('w-download').handlers.click();
  assert.equal(get('w-status-title').textContent,'Operation stopped.');assert.match(get('w-status').textContent,/Unsupported or incomplete/);
  assert.equal(get('w-manifest').value,'bad.json','failed source survives refresh');
  assert.equal(get('w-download').disabled,false);
  vm.runInContext(`for(const key of Object.keys(TEXTS.en).filter(k=>k.startsWith('w')))for(const locale of Object.keys(TEXTS))if(!TEXTS[locale][key])throw Error(locale+':'+key)`,context);
  vm.runInContext(`for(const key of Object.keys(TEXTS.en)){if(!TEXTS.ru[key])throw Error('missing Russian: '+key);const placeholders=s=>[...s.matchAll(/\\{(\\w+)\\}/g)].map(v=>v[1]).sort().join(',');if(placeholders(TEXTS.en[key])!==placeholders(TEXTS.ru[key]))throw Error('Russian placeholders: '+key);}if(resolveLanguage('ru-RU')!=='ru')throw Error('Russian locale not selected')`,context);
  vm.runInContext('openSettings()',context);
  get('s-game-dir').value='E:/Battle.net/World of Warcraft';
  const savesBefore=calls.filter(c=>c.cmd==='save_settings').length;
  await get('official-connect').handlers.click();
  assert.match(get('official-result').textContent,/70790/);
  assert.match(get('official-result').textContent,/70658/);
  assert.equal(calls.filter(c=>c.cmd==='save_settings').length,savesBefore,'incompatible EXE must not be connected');
  officialReply={...officialReply,version:'1.60.1.70658',ready:true,status:'official_ready'};
  get('s-address').value='127.0.0.1'; get('s-portal').value='trinity.actual.battle.net';
  await get('official-connect').handlers.click();
  const connected=calls.filter(c=>c.cmd==='save_settings').at(-1).args.settings;
  assert.equal(connected.protectClientFiles,true);
  assert.equal(connected.gameDir,officialReply.gameDir);
  assert.equal(connected.server.address,'127.0.0.1');
  assert.equal(get('w-repair').disabled,true); assert.equal(get('w-download').disabled,true);
  assert.equal(get('quick-repair').hidden,false,'separate managed-client downloads remain available');
  const writesBefore=calls.filter(c=>['client_work','install_content','rollback_content'].includes(c.cmd)).length;
  await get('w-repair').handlers.click(); await get('w-download').handlers.click();
  await get('w-recover').handlers.click(); await get('content-install').handlers.click(); await get('content-rollback').handlers.click();
  assert.equal(calls.filter(c=>['client_work','install_content','rollback_content'].includes(c.cmd)).length,writesBefore,'official mode must not invoke mutations');
  state.officialClient={...officialReply,ready:false,status:'official_mismatch',version:'1.60.1.70790'};
  await vm.runInContext('refresh()',context);
  assert.equal(get('play').disabled,true,'incompatible official build must block Play');
  vm.runInContext(`for(const key of Object.keys(TEXTS.en).filter(k=>k.startsWith('official')))for(const locale of Object.keys(TEXTS))if(!TEXTS[locale][key])throw Error(locale+':'+key)`,context);
  vm.runInContext(`for(const key of Object.keys(TEXTS.en).filter(k=>k.startsWith('n') && k!=='news' && k!=='newsTag' && k!=='noAccount'))for(const locale of Object.keys(TEXTS))if(!TEXTS[locale][key])throw Error(locale+':'+key)`,context);
  await get('nav-downloads').handlers.click();
  assert.equal(get('native-page').hidden,false);
  get('n-dir').value='';
  const nativeBefore=calls.filter(c=>c.cmd==='native_client_work').length;
  await get('n-download').handlers.click();
  assert.equal(calls.filter(c=>c.cmd==='native_client_work').length,nativeBefore);
  get('n-dir').value='E:/managed';get('n-locale').value='ruRU';get('n-hd').checked=true;
  const oldServer=structuredClone(state.settings.server),oldDir=state.settings.gameDir;
  await get('n-download').handlers.click();
  const native=calls.find(c=>c.cmd==='native_client_work');
  assert.deepEqual(JSON.parse(JSON.stringify(native.args.request)),{action:'download',directory:'E:/managed',locale:'ruRU',highRes:true});
  assert.deepEqual(state.settings.server,oldServer,'content sources cannot replace the login profile');
  assert.equal(state.settings.gameDir,oldDir,'download completion does not silently switch the active client');
  assert.equal(get('n-connect').disabled,false);
  state.settings.server.clientBuild=70658;
  officialReply={...officialReply,gameDir:'E:/managed/_forever_',ready:true,status:'official_ready',version:'1.60.1.70658'};
  await get('n-connect').handlers.click();
  const nativeConnected=calls.filter(c=>c.cmd==='save_settings').at(-1).args.settings;
  assert.equal(nativeConnected.gameDir,'E:/managed/_forever_');
  assert.equal(nativeConnected.locale,'ruRU');
  assert.equal(nativeConnected.protectClientFiles,true);
  assert.equal(nativeConnected.server.portal,oldServer.portal);
  assert.equal(nativeConnected.server.address,oldServer.address);
  console.log('Launcher UI: five languages, official EXE mismatch, protected installation, legacy workshop and busy-game gates passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
