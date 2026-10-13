const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8'),start=html.indexOf('const themePreference='),end=html.indexOf("const tileTemplate=",start);assert(start>=0&&end>start);
for(const initial of ['auto','light','dark']){
 let handler;const preference={matches:false,addEventListener:(name,callback)=>{assert.equal(name,'change');handler=callback}},root={dataset:{mapTheme:initial}};
 let changed;const select={value:'auto',addEventListener:(name,callback)=>{assert.equal(name,'change');changed=callback}};
 const context=vm.createContext({document:{documentElement:root,getElementById:()=>select},window:{matchMedia:q=>{assert.equal(q,'(prefers-color-scheme: dark)');return preference}}});
 vm.runInContext(html.slice(start,end),context);
 assert.equal(root.dataset.mapPalette,initial==='auto'?'light':initial);
 preference.matches=true;handler();assert.equal(root.dataset.mapPalette,initial==='auto'?'dark':initial);
 vm.runInContext("setMapTheme('light')",context);assert.equal(root.dataset.mapPalette,'light');preference.matches=false;handler();assert.equal(root.dataset.mapPalette,'light');
 vm.runInContext("setMapTheme('dark')",context);assert.equal(root.dataset.mapPalette,'dark');
 vm.runInContext("setMapTheme('auto')",context);assert.equal(root.dataset.mapPalette,'light');
 select.value='dark';changed();assert.equal(root.dataset.mapPalette,'dark');
 vm.runInContext("setMapTheme('light')",context);assert.equal(root.dataset.mapPalette,'dark');assert.equal(select.value,'dark');
 select.value='light';changed();assert.equal(root.dataset.mapPalette,'light');
 select.value='auto';changed();preference.matches=true;handler();assert.equal(root.dataset.mapPalette,'dark');assert.equal(select.value,'auto');
}
assert(html.includes('html[data-map-palette="dark"] .leaflet-tile-pane{filter:'));
assert(!html.includes('html[data-map-palette="dark"] .leaflet-marker-pane'));
console.log('PASS live toolbar selection, no request/restart, default refresh respects local choice, auto preference changes and basemap-only styling');
