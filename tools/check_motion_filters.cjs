/* Exercise shipped filter/color logic and counts with Leaflet marker fixtures. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8');
const start=html.indexOf('const motionPalette='),end=html.indexOf('function motionStateHtml',start);
let clock=100000,selected=['all'],colored=false,visible=new Set(['a','b','c']),nodes={};
const controls=['all','steady_flight','climbing','descending','turning_left','turning_right','decelerating','accelerating','warming_up','stale','other'].map(value=>({value}));
const node=id=>nodes[id]??=(id==='motion-colors'?{get checked(){return colored}}:{});
const markers=new Map(['a','b','c'].map((key,i)=>[key,{bridgeVisual:{degrees:90,flags:{origin:true}},getLatLng:()=>({lat:i,lon:0}),addTo:()=>visible.add(key),setIcon:icon=>{node(key).icon=icon}}]));
const ctx=vm.createContext({Date:{now:()=>clock},Number,Object,Set,inputSource:'sbs_30003',motionFreshSeconds:15,motionStates:{a:{quality:'supported',position_age_seconds:0,fetched_at:100,primitives:[{name:'descending'},{name:'decelerating'}]},b:{quality:'supported',position_age_seconds:0,fetched_at:100,primitives:[{name:'steady_flight'}]},c:{quality:'warming_up',position_age_seconds:0,fetched_at:100,primitives:[]}},markers,map:{hasLayer:m=>visible.has([...markers].find(([k,v])=>v===m)[0]),removeLayer:m=>visible.delete([...markers].find(([k,v])=>v===m)[0])},L:{latLngBounds:points=>points},lastBounds:null,icon:(d,flags)=>flags,document:{getElementById:node,querySelectorAll:selector=>selector.endsWith(':checked')?controls.filter(el=>selected.includes(el.value)):controls}});
vm.runInContext(html.slice(start,end),ctx);const run=s=>vm.runInContext(s,ctx);
run('applyMotionView()');assert.equal(visible.size,3);assert.equal(nodes['motion-count-descending'].textContent,1);
selected=['descending'];run('applyMotionView()');assert.deepEqual([...visible],['a']);assert.equal(ctx.lastBounds.length,1);
selected=['descending','steady_flight'];colored=true;run('applyMotionView()');assert.equal(visible.size,2);assert.equal(nodes.a.icon.motionColor,'#ff9b46');assert(nodes.a.icon.origin);
selected=[];run('applyMotionView()');assert.equal(visible.size,0);assert.equal(ctx.lastBounds,null);
selected=['all'];clock+=16000;run('applyMotionView()');assert.equal(nodes['motion-count-stale'].textContent,3);assert.equal(nodes['motion-count-descending'].textContent,0);assert.equal(nodes.a.icon.motionColor,null);
ctx.inputSource='swim_tfms';selected=[];run('applyMotionView()');assert.equal(visible.size,3);assert(nodes['motion-options'].hidden);
console.log('PASS any-label filters, empty/all selections, viewport fit, counts, priority colors, badges, local freshness and source exclusion');

// Geometry labels share the any-label filters and take color precedence.
run("inputSource='sbs_30003'; motionStates.a={quality:'supported',position_age_seconds:0,fetched_at:Date.now()/1000,primitives:[{name:'descending'}],patterns:[{name:'racetrack',status:'established'}]}");
assert(run("motionLabels('a')").includes('racetrack'));
assert(run("matchesMotion('a',['racetrack'])"));
assert.equal(run("motionColor('a',true)"),'#ef80e6');
clock+=16000;assert(!run("motionLabels('a')").includes('racetrack'));
console.log('PASS geometry filtering, color precedence and stale suppression');
