const fs=require('fs'),vm=require('vm'),assert=require('assert');
const text=fs.readFileSync(process.argv[2],'utf8');const start=text.indexOf('let loadedSource=null;'),end=text.indexOf('async function refresh(){',start);
for(const faa of [false,true]){
 const c=vm.createContext({faaLocalView:faa});vm.runInContext(text.slice(start,end),c);
 const initial=faa?'swim_sfdps':'sbs_30003';
 assert.equal(vm.runInContext('sourceChanged(null)',c),false);
 c.s={source:initial};assert.equal(vm.runInContext('sourceChanged(s)',c),false);assert.equal(vm.runInContext('sourceChanged(s)',c),false);
 c.s={source:faa?'sbs_30003':'swim_sfdps'};assert.equal(vm.runInContext('sourceChanged(s)',c),true);
}
assert(text.indexOf('if(sourceChanged(status))')<text.indexOf('if(!ar.ok)throw new Error(`aircraft.json HTTP'));
console.log('PASS source changes detected before disabled raw-feed error, both directions');
