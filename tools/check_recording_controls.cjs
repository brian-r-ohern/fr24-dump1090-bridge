const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2],'utf8');
const code=source.slice(source.indexOf('function recordingSize('),source.indexOf('let loadedSource=null;'));
assert(code.includes('async function recordingAction'));
const elements=new Map();
const document={getElementById(id){if(!elements.has(id))elements.set(id,{textContent:'',disabled:false,open:false,handlers:{},addEventListener(event,fn){this.handlers[event]=fn}});return elements.get(id)}};
let data={enabled:true,retained_snapshots:15,retained_samples:200,recording_bytes:1048576,limit_bytes:2147483648,queue_bytes:0,snapshots_dropped:0,write_errors:0,ends_at:1800000000,process_rss_bytes:1000000,history:{estimated_memory_bytes:500000,retained_samples:100}};
const calls=[],window={location:{href:''}};
const ctx=vm.createContext({document,window,Number,Date,setInterval(){},fetch:async(path,options)=>{calls.push({path,options});return{ok:true,json:async()=>data}}});
vm.runInContext(code,ctx);
(async()=>{
 await ctx.refreshRecording();assert(elements.get('recording-start').disabled);assert(!elements.get('recording-stop').disabled);assert(elements.get('recording-status').textContent.includes('200 positioned samples'));
 data.enabled=false;await ctx.refreshRecording();assert(!elements.get('recording-start').disabled);assert(elements.get('recording-stop').disabled);
 await ctx.recordingAction('start');const post=calls.find(x=>x.path==='recording/start');assert.equal(post.options.method,'POST');assert.equal(post.options.headers['Content-Type'],'application/json');assert.equal(post.options.body,'{}');
 elements.get('recording-export').handlers.click();assert.equal(window.location.href,'recording/export?download=1&format=geojson');
 elements.get('recording-replay').handlers.click();assert.equal(window.location.href,'recording/export?download=1&format=jsonl');
 data={...data,retained_snapshots:0,last_error:'Storage limit'};await ctx.refreshRecording();assert(elements.get('recording-export').disabled);assert(elements.get('recording-status').textContent.includes('Storage limit'));
 console.log('PASS shipped recording controls: start/stop state, explicit downloads, RAM/disk counts and error display');
})().catch(error=>{console.error(error);process.exitCode=1});
