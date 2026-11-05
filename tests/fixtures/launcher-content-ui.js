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
const state={settings:{gameDir:'E:/client/_classic_beta_',language:'en',locale:'ruRU',server:{website:'',name:'Forever'}},gameFound:true,gameVersion:'1.60.1.70532',email:null,platform:'windows',version:'test',locales:['ruRU'],runners:[],playing:false};
async function invoke(cmd,args){
  calls.push({cmd,args});
  if(cmd==='get_state')return structuredClone(state);
  if(cmd==='server_status')return {online:true,login:true};
  if(cmd==='news')return [];
  if(cmd==='checks')return {hosts:true,certificate:true};
  if(cmd==='content_catalog')return [{name:'Dalaran',status:'experimental'}];
  if(cmd==='content_status')return {installed:null,recoveryNeeded:false,backup:null};
  if(cmd==='inspect_content')return selected;
  if(cmd==='install_content')return {installed:'Owned zone 1',recoveryNeeded:false,backup:'E:/backup'};
  if(cmd==='rollback_content')return {installed:null,recoveryNeeded:false,backup:null};
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
  console.log('Content UI: experimental gate, install, rollback and client selection passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
