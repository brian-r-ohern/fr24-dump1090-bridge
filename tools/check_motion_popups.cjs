/* Exercise shipped motion popup/cache code, not a duplicate implementation. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8'),start=html.indexOf('let motionFreshSeconds='),end=html.indexOf('function popup(',start);
assert(start>=0&&end>start);
let now=Date.parse('2026-10-10T18:00:00Z'),requests=0,fail=false;
class Clock extends Date{static now(){return now}}
const response={fresh_seconds:15,aircraft:{abc123:{quality:'supported',position_age_seconds:0,primitives:[{name:'steady_flight',duration_seconds:60},{name:'level_altitude',duration_seconds:60},{name:'stable_speed',duration_seconds:60},{name:'stable_course',duration_seconds:60}],metrics:{turn_rate_deg_s:0,vertical_rate_fpm:0}}}};
const ctx=vm.createContext({Date:Clock,Math,Number,Object,AbortController,setTimeout,clearTimeout,inputSource:'sbs_30003',esc:v=>String(v).replaceAll('<','&lt;').replaceAll('>','&gt;'),fetch:async()=>{requests++;if(fail)throw Error('offline');return{ok:true,json:async()=>structuredClone(response)}}});
vm.runInContext(html.slice(start,end),ctx);
const run=code=>vm.runInContext(code,ctx);
(async()=>{
 assert(run("motionStateHtml('abc123')").includes('Collecting independent positions'));
 await run('refreshMotionStates()');assert.equal(requests,1);
 let out=run("motionStateHtml('abc123')");assert(out.includes('Steady flight'));assert(!out.includes('Stable speed'));assert(out.includes('Observed turn rate'));
 await run('refreshMotionStates()');assert.equal(requests,1);
 now+=16000;out=run("motionStateHtml('abc123')");assert(out.includes('Position stale'));assert(!out.includes('Observed turn rate'));
 response.aircraft.abc123.quality='warming_up';await run('refreshMotionStates()');assert(run("motionStateHtml('abc123')").includes('Warming up'));
 now+=6000;response.aircraft.abc123.quality='supported';response.aircraft.abc123.primitives=[{name:'turning_left',duration_seconds:35}];response.aircraft.abc123.metrics.turn_rate_deg_s=-1;
 await run('refreshMotionStates()');assert(run("motionStateHtml('abc123')").includes('Turning left'));
 now+=6000;fail=true;await run('refreshMotionStates()');assert(run("motionStateHtml('abc123')").includes('Collecting independent positions'));
 for(const source of ['swim_tfms','flights_js']){ctx.inputSource=source;const before=requests;now+=6000;await run('refreshMotionStates()');assert.equal(requests,before);assert.equal(run("motionStateHtml('abc123')"),'')}
 ctx.inputSource='swim_sfdps';ctx.verboseMotion=true;
 run("motionStates.abc123={quality:'supported',position_age_seconds:0,fetched_at:Date.now()/1000,primitives:[],metrics:{ground_speed_knots:200},speed_diagnostics:{stable_speed:false,blockers:['excessive_speed_variation'],reported_speed_semantics:'reported_speed_unverified',reported_speed_knots:220,latest_leg_derived_minus_latest_reported_knots:-20,derived_speeds_knots:{min:180,median:200,max:240},report_intervals_seconds:{min:10,median:12,max:14},usable_speed_samples:8,speed_span_seconds:84,reported_speed_timing:'field_receipt'}}");
 out=run("motionStateHtml('abc123')");assert(out.includes('Speed diagnostics'));assert(out.includes('meaning unverified'));assert(out.includes('excessive speed variation'));assert(out.includes('180 / 200 / 240'));
 ctx.verboseMotion=false;assert(!run("motionStateHtml('abc123')").includes('Speed diagnostics'));
 assert(html.includes('refreshMotionStates();for(const ac'));
 console.log('PASS shipped motion labels, component collapse, local staleness, warming-up, five-second fetch cadence, failure isolation and excluded sources');
})().catch(e=>{console.error(e);process.exitCode=1});
