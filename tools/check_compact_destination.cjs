const fs=require('fs'),vm=require('vm'),assert=require('assert');
const s=fs.readFileSync(process.argv[2],'utf8');
const m=s.match(/class="ac-compact-destination">\$\{esc\(([^}]+)\)\}/);assert(m);
for(const [ac,t,want] of [[{route_destination:'KSFO'},{},'KSFO'],[{}, {route_destination:'KORD'},'KORD'],[{}, {},'—'],[{destination:'KBOS'},{},'KBOS']])assert.equal(vm.runInNewContext(m[1],{ac,t,destinationAirport:'KSYR'}),want);
console.log('PASS compact destination: FAA, enrichment, alternate field, unknown without home-airport fallback');
