/* Exercise the shipped altitude-selection handlers without a browser dependency.
 * node tools/check_density_controls.cjs /tmp/bridge-map.html
 */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8');
const start=html.indexOf('const bandInputs='),end=html.indexOf('const envelopeLayers=',start);
assert(start>=0&&end>start,'Find shipped altitude control handlers');
const inputs=['low','middle','high','all'].map(value=>({value,checked:value==='all',handlers:{},addEventListener(name,fn){this.handlers[name]=fn}}));
let updates=0;
const context=vm.createContext({document:{querySelectorAll:selector=>{assert.equal(selector,'.density-band');return inputs}},markDensityChanged:()=>updates++});
vm.runInContext(html.slice(start,end),context);
const selection=()=>vm.runInContext('densitySelection()',context);
const change=(value,checked)=>{const input=inputs.find(x=>x.value===value);input.checked=checked;input.handlers.change()};
assert.equal(selection(),'all');
change('low',true);assert.equal(selection(),'low');assert(!inputs[3].checked);
change('high',true);assert.equal(selection(),'low,high');
change('middle',true);assert.equal(selection(),'low,middle,high');
change('all',true);assert.equal(selection(),'all');assert(inputs.slice(0,3).every(x=>!x.checked));
change('all',false);assert.equal(selection(),'none');
change('middle',true);assert.equal(selection(),'middle');
change('middle',false);assert.equal(selection(),'none');
assert.equal(updates,7);
console.log('PASS shipped altitude controls: All, combinations, clearing and no selection');
