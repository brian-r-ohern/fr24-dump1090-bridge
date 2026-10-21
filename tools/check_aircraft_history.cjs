const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8'),ctx=vm.createContext({Number,Infinity});
const start=html.indexOf('function historySegments('),end=html.indexOf('async function refreshAnalysisTrail',start);
vm.runInContext(html.slice(start,end),ctx);
ctx.samples=[{t:1,lat:42,lon:-77,segment:1},{t:2,lat:43,lon:-77,segment:1},{t:50,lat:44,lon:-77,segment:2,break_reason:'observation_gap'},{t:60,lat:45,lon:-77,segment:2}];
let runs=vm.runInContext('historySegments(samples)',ctx);assert.equal(runs.length,2);assert.equal(runs[0].length,2);assert.equal(runs[1].length,2);
runs=vm.runInContext('historySegments(samples,2,50)',ctx);assert.equal(runs.length,2);assert.equal(runs[0].length,1);
ctx.samples=[{t:1,lat:42,lon:179,segment:1},{t:2,lat:42,lon:-179,segment:1}];assert.equal(vm.runInContext('historySegments(samples)',ctx).length,2);
assert(html.includes('aircraft-history?track_id='));assert(html.includes('aircraft-history?download=1'));assert(html.includes('pattern.first_supported,pattern.last_supported'));
console.log('PASS selected history segments, gap and antimeridian breaks, evidence interval and export routes');

assert(html.includes('#history-controls{display:flex;'));assert(html.includes('id="history-controls"'));
