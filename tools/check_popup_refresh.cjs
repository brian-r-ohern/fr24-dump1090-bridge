const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2],'utf8');
const code=source.slice(source.indexOf('function updateAircraftPopup('),source.indexOf('function popup('));
function detail(key,open=false){return {dataset:{popupSection:key},open,querySelector(){return {focus(){focused=key}}}}}
let focused=null;
function element(details,scrollTop=0){const content={scrollTop};return {details,content,querySelectorAll(){return details},querySelector(){return content},contains(x){return x===active}}}
let active={closest(){return {dataset:{popupSection:'speed-diagnostics'}}}};
let live=element([detail('speed-diagnostics',true),detail('geometry-orbit',false)],137);
const document={activeElement:active,createElement(){let rows=[];return {set innerHTML(value){rows=JSON.parse(value).map(x=>detail(x.key,x.open))},get innerHTML(){return JSON.stringify(rows.map(x=>({key:x.dataset.popupSection,open:x.open})))},content:{querySelectorAll(){return rows}}}}};
const marker={getPopup(){return {getElement(){return live}}},setPopupContent(html){this.html=html;live=element(JSON.parse(html).map(x=>detail(x.key,x.open)))}};
const ctx=vm.createContext({Map,document});vm.runInContext(code,ctx);ctx.marker=marker;
const update=rows=>{ctx.html=JSON.stringify(rows.map(key=>({key,open:false})));vm.runInContext('updateAircraftPopup(marker,html)',ctx)};
update(['geometry-orbit','speed-diagnostics']);assert(live.details[1].open);assert(!live.details[0].open);assert.equal(live.content.scrollTop,137);assert.equal(focused,'speed-diagnostics');
live.details[1].open=false;update(['speed-diagnostics']);assert(!live.details[0].open);
live.details[0].open=true;update([]);update(['speed-diagnostics']);assert(live.details[0].open);
const other={getPopup(){return null},setPopupContent(html){this.html=html}};ctx.marker=other;update(['speed-diagnostics']);assert(!JSON.parse(other.html)[0].open);
assert(source.includes('updateAircraftPopup(m,popup('));assert(source.includes('data-popup-section="speed-diagnostics"'));
// Every dynamically rendered popup facet needs a stable persistence key.
const popupRenderers=source.slice(source.indexOf('function modeledArrivalHtml('),source.indexOf('function popup('));
const facets=[...popupRenderers.matchAll(/<details\b[^>]*>/g)].map(match=>match[0]);
assert(facets.length>=3);
for(const facet of facets)assert(facet.includes('data-popup-section='),`Unkeyed popup facet: ${facet}`);
assert(source.includes('data-popup-section="touchdown-assumptions"'));
for(const inputSource of ['sbs_30003','aircraft_json','swim_sfdps']){
  ctx.inputSource=inputSource;
  live=element([detail('touchdown-assumptions',true),detail('speed-diagnostics',true)],95);
  const ownMarker={getPopup(){return {getElement(){return live}}},setPopupContent(html){live=element(JSON.parse(html).map(x=>detail(x.key,x.open)))}};
  ctx.marker=ownMarker;
  update(['speed-diagnostics','touchdown-assumptions']);
  assert(live.details.find(x=>x.dataset.popupSection==='touchdown-assumptions').open,inputSource);
  assert.equal(live.content.scrollTop,95);
  live.details.find(x=>x.dataset.popupSection==='touchdown-assumptions').open=false;
  update(['touchdown-assumptions']);assert(!live.details[0].open,inputSource);
  live.details[0].open=true;update([]);update(['touchdown-assumptions']);assert(live.details[0].open,inputSource);
}
console.log('PASS keyed touchdown assumptions for SBS/aircraft.json/SFDPS, popup expansion/collapse, reordered and temporarily absent sections, per-marker isolation, scroll and focus across refresh');
