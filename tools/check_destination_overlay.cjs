const fs=require('fs'),vm=require('vm'),assert=require('assert');
const text=fs.readFileSync(process.argv[2],'utf8'),start=text.indexOf('function updateSelectedDestination(){'),end=text.indexOf('let selectedAnalysisKey=',start);
let open=true,code='KBOS',lat=1,lines=[],crosses=[];
const layer={clearLayers(){lines=[];crosses=[]}};
const markers=new Map([['a',{isPopupOpen:()=>open,getLatLng:()=>[lat,2],bridgeAircraft:{route_destination:'KBOS'}}]]);
const c=vm.createContext({selectedDestination:layer,selectedAnalysisKey:'a',markers,trackerFor:()=>({}),destinationAirports:new Map([['KBOS',{lat:42,lon:-71}]]),esc:x=>x,L:{polyline(p,o){lines.push({p,o});return{addTo(){}}},divIcon:o=>o,marker(p,o){crosses.push(p);return{bindTooltip(){return this},addTo(){}}}}});
vm.runInContext(text.slice(start,end),c);vm.runInContext('updateSelectedDestination()',c);assert.equal(lines.length,1);assert.equal(crosses.length,1);assert.equal(lines[0].o.dashArray,'7 7');lat=3;vm.runInContext('updateSelectedDestination()',c);assert.equal(lines[0].p[0][0],3);open=false;vm.runInContext('updateSelectedDestination()',c);assert.equal(lines.length,1);c.selectedAnalysisKey='b';vm.runInContext('updateSelectedDestination()',c);assert.equal(lines.length,0);c.selectedAnalysisKey='a';open=true;markers.get('a').bridgeAircraft.route_destination='UNKNOWN';vm.runInContext('updateSelectedDestination()',c);assert.equal(lines.length,0);
assert(text.includes('id="recording-control" class="analysis-controls" hidden'));assert(text.includes('hidden=c?.development_recording!==true'));
console.log('PASS destination persists with closed popup, follows selection and movement, clears for unknown/missing selection, and recording visibility gate');
