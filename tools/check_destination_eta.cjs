/* Exercise the shipped map ETA and airport fetching without a browser. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8');
const start=html.indexOf('const destinationAirports='),end=html.indexOf('function bearing(a,b)',start);
assert(start>=0&&end>start);
let requests=[],responses={airports:{SYR:{icao:'KSYR',lat:43.11,lon:-76.11},UNKNOWN:null}},failing=false;
const now=Date.parse('2026-10-10T23:50:00Z');
class Clock extends Date {constructor(value){super(value===undefined?now:value)}static now(){return now}}
const context=vm.createContext({Date:Clock,Math,Number,String,Set,Map,encodeURIComponent,
 inputSource:'sbs_30003',trackerFor:key=>key==='abc123'?{route_destination:'SYR'}:{},
 esc:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
 fetch:async url=>{requests.push(url);return{ok:!failing,json:async()=>responses}}});
vm.runInContext(html.slice(start,end),context);
const run=code=>vm.runInContext(code,context);
run("destinationAirports.set('TEST',{lat:0,lon:1})");
let estimate=run("destinationEstimate({lat:0,lon:0,gs:120},{route_destination:'TEST'})");
assert(Math.abs(estimate.distanceNm-60.04046)<.001);
assert(Math.abs(estimate.minutes-30.02023)<.001);
assert(Math.abs(estimate.arrivalMs-(now+30.02023*60000))<2);
for(const fields of ["lat:null,lon:0,gs:120","lat:0,lon:null,gs:120","lat:0,lon:0,gs:null","lat:0,lon:0,gs:0","lat:0,lon:0,gs:-1","lat:0,lon:0,gs:'120'","lat:91,lon:0,gs:120","lat:0,lon:0,gs:NaN","lat:0,lon:0,gs:120,alt_baro:'ground'"])
 assert.equal(run(`destinationEstimate({${fields}},{route_destination:'TEST'})`),null);
assert.equal(run("destinationEstimate({lat:0,lon:0,gs:120},{route_destination:'MISSING'})"),null);
const rendered=run("destinationEstimateHtml({lat:0,lon:0,gs:120},{route_destination:'TEST'})");
assert(rendered.includes('60.0 NM'));assert(rendered.includes('~30 min'));assert(rendered.includes('2026-10-11 00:20 UTC'));assert(rendered.includes('ETA · current ground speed'));
assert(run("destinationEstimateHtml({lat:0,lon:1,gs:120},{route_destination:'TEST'})").includes('&lt;1 min'));
run("destinationAirports.set('DATE',{lat:0,lon:-170})");
assert(Math.abs(run("destinationEstimate({lat:0,lon:170,gs:600},{route_destination:'DATE'}).minutes")-120.0809)<.002);
run("destinationAirports.set('ANTI',{lat:0,lon:180})");assert(Number.isFinite(run("destinationEstimate({lat:0,lon:0,gs:600},{route_destination:'ANTI'}).minutes")));
context.inputSource='swim_tfms';assert(run("destinationEstimate({lat:0,lon:0,gs:120,route_destination:'TEST'},{route_destination:'MISSING'})"));
context.inputSource='sbs_30003';
// Render the real popup: map-only ETA adds rows without changing aircraft data.
const popup=html.slice(html.indexOf('let motionFreshSeconds='),html.indexOf('function icon('));
Object.assign(context,{destinationAirport:null,altitude:v=>String(v),fmt:v=>String(v),signed:v=>String(v),cardinalDirection:()=>'',trackerFor:()=>({route_destination:'TEST'})});
vm.runInContext(popup,context);
assert(run("popup({hex:'abc123',lat:0,lon:0,gs:120},{},'abc123',{degrees:null})").includes('ETA · current ground speed'));
assert(!run("popup({hex:'abc123',lat:0,lon:0,gs:0},{},'abc123',{degrees:null})").includes('ETA · current ground speed'));
assert(run("destinationEstimateHtml({lat:0,lon:0,gs:120,seen_pos:31},{route_destination:'TEST'})").includes('last known position (31s old)'));
assert(run("destinationEstimateHtml({lat:0,lon:0,gs:120},{route_destination:'TEST'})").includes('position age unknown'));
assert(!run("destinationEstimateHtml({lat:0,lon:0,gs:120,seen_pos:1},{route_destination:'TEST'})").includes('last known position'));
context.trackerFor=key=>key==='abc123'?{route_destination:'SYR'}:{};
(async()=>{
 await run("refreshDestinationAirports([{hex:'abc123'}])");assert.equal(requests.length,1);assert(requests[0].includes('codes=SYR'));
 await run("refreshDestinationAirports([{hex:'abc123'}])");assert.equal(requests.length,1);
 context.inputSource='swim_tfms';await run("refreshDestinationAirports([{route_destination:'UNKNOWN'}])");assert.equal(requests.length,2);
 await run("refreshDestinationAirports([{route_destination:'UNKNOWN'}])");assert.equal(requests.length,2);
 failing=true;await run("refreshDestinationAirports([{route_destination:'RETRY'}])");assert.equal(requests.length,3);
 await run("refreshDestinationAirports([{route_destination:'RETRY'}])");assert.equal(requests.length,3);
 console.log('PASS shipped direct-distance ETA, UTC rollover, invalid/missing inputs, ground suppression, antimeridian, TFMS, real popup, cached airport subsets and lookup-failure fallback');
})().catch(e=>{console.error(e);process.exitCode=1});
