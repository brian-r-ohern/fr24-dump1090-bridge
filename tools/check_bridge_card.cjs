const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element { dispatchEvent(e){events.push(e);} attachShadow(){this.shadowRoot={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>({textContent:''})};} }
const registry=new Map(),storage=new Map(),events=[];
const context=vm.createContext({document:{createElement:k=>new (registry.get(k))()},CustomEvent:class{constructor(type,config){this.type=type;Object.assign(this,config)}},HTMLElement:Element,customElements:{get:k=>registry.get(k),define:(k,v)=>registry.set(k,v)},window:{location:{pathname:'/dashboard-test/home',search:''},customCards:[],dispatchEvent:e=>events.push(e)},sessionStorage:{setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},history:{pushState:(a,b,p)=>events.push(p)},Event:class{constructor(type){this.type=type}},Date});
vm.runInContext(fs.readFileSync('dashboard/aircraft-bridge-card.js','utf8'),context);
const Card=registry.get('aircraft-bridge-card'),card=new Card();
assert.throws(()=>card.setConfig({entity:'sensor.a',ingress_path:'//evil.example'}));
card.setConfig({entity:'sensor.a',ingress_path:'/hassio/ingress/local_fr24_dump1090'});
card.hass={states:{'sensor.a':{state:'ok',attributes:{source:'swim_tfms',build_version:'0.6.9',feed_status:'ok',feed_consumers:{external_count:2,clients:[{label:'<script>',last_seen_age_seconds:1}]}}}}};
assert(card.shadowRoot.innerHTML.includes('&lt;script&gt;'));assert(card.shadowRoot.innerHTML.includes('0.6.9'));
card.navigate('status-page');const handoff=JSON.parse(storage.get('aircraft-bridge-navigation'));assert.equal(handoff.target,'status-page');const routeEvent=events.find(e=>e.type==='location-changed');assert.equal(routeEvent.detail.replace,false);
const html=fs.readFileSync('fr24-dump1090/fr24_dump1090.py','utf8');const code=html.split('CARD_NAV_SCRIPT = r"""<script>')[1].split('</script>')[0];
let replaced=null;const parent={location:{pathname:handoff.path}},location={replace:p=>replaced=p};
vm.runInNewContext(code,{sessionStorage:{getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},parent,location,Date});assert.equal(replaced,'status-page');assert.equal(storage.size,0);
storage.set('aircraft-bridge-navigation',JSON.stringify({...handoff,target:'https://evil.example'}));replaced=null;
vm.runInNewContext(code,{sessionStorage:{getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},parent,location,Date});assert.equal(replaced,null);
card.hass={states:{'sensor.a':{state:'unavailable',attributes:{}}}};assert(card.shadowRoot.innerHTML.includes('Unavailable'));
console.log('PASS card rendering, escaping, unavailable entity and constrained Ingress handoff');

card.setConfig({entity:'sensor.a'});
card.hass={states:{'sensor.a':{state:'ok',attributes:{aircraft_bridge:true,source:'swim_tfms',build_version:'0.6.9.1',ingress_path:'/hassio/ingress/local_fr24_dump1090'}}}};
assert(card.shadowRoot.innerHTML.includes('class="ok">ok'));
assert(card.shadowRoot.innerHTML.includes('Aircraft Bridge · TFMS'));
assert(!card.shadowRoot.innerHTML.includes('<td>Message rate</td>'));
assert.equal(Card.getStubConfig(card._hass).entity,'sensor.a');
card.navigate('');assert(events.includes('/app/local_fr24_dump1090'));
card.hass={states:{'sensor.a':{state:'ok',attributes:{source:'sbs_30003',message_rate_per_second:300}}}};
assert(card.shadowRoot.innerHTML.includes('Aircraft Bridge · SBS'));
assert(card.shadowRoot.innerHTML.includes('<td>Message rate</td>'));
const editor=Card.getConfigElement();
let nodes={entity:{},title:{}};
editor.attachShadow=()=>{editor.shadowRoot={innerHTML:'',getElementById:k=>nodes[k]};};
editor.setConfig({entity:'sensor.a'});editor.hass=card._hass;
nodes.title.onchange({target:{value:'My Bridge'}});
const event=events.find(e=>e.type==='config-changed');assert.equal(event.detail.config.title,'My Bridge');assert.equal(event.bubbles,true);assert.equal(event.composed,true);
console.log('PASS feed-state fallback, automatic source title, optional metrics, picker stub, visual editor and entity Ingress path');

for(const target of ['', 'status-page', 'settings']) {
  card.setConfig({entity:'sensor.a', ingress_path:'/hassio/ingress/local_fr24_dump1090'});
  card.navigate(target);
  const nav=events.filter(e=>e.type==='location-changed').at(-1);
  assert.equal(nav.detail.replace,false);
  assert(events.includes('/app/local_fr24_dump1090'));
  if(target) {
    const pending=JSON.parse(storage.get('aircraft-bridge-navigation'));
    assert.equal(pending.target,target);
    replaced=null;
    vm.runInNewContext(code,{sessionStorage:{getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},parent,location,Date});
    assert.equal(replaced,target);
  } else assert(!storage.has('aircraft-bridge-navigation'));
}
console.log('PASS all three buttons dispatch HA routing options and preserve constrained target handoff');

// Model HA's panel selection: an obsolete root returns to the dashboard.
const resolvePanel=path=>Object.hasOwn(card._hass.panels,path.split('/')[1])?path:'/dashboard-test/home';
for(const slug of ['local_fr24_dump1090','e8a948e6_fr24_dump1090']) {
  for(const savedPath of ['/hassio/ingress/'+slug,'/app/'+slug]) {
    card.setConfig({entity:'sensor.a',ingress_path:savedPath});
    card.hass={panels:{app:{component_name:'app'}},states:{'sensor.a':{state:'ok',attributes:{}}}};
    for(const target of ['', 'status-page', 'settings']) {
      card.navigate(target);
      const path=events.filter(e=>typeof e==='string').at(-1);
      assert.equal(resolvePanel(path),'/app/'+slug);
      if(target) {
        const pending=JSON.parse(storage.get('aircraft-bridge-navigation'));
        assert.equal(pending.path,path);
        replaced=null;
        vm.runInNewContext(code,{sessionStorage:{getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},parent:{location:{pathname:path}},location,Date});
        assert.equal(replaced,target);
      } else assert(!storage.has('aircraft-bridge-navigation'));
    }
  }
}
card.setConfig({entity:'sensor.a',ingress_path:'/app/local_fr24_dump1090'});
card.hass={panels:{hassio:{component_name:'hassio'}},states:{'sensor.a':{state:'ok',attributes:{}}}};
card.navigate('');assert.equal(events.filter(e=>typeof e==='string').at(-1),'/hassio/ingress/local_fr24_dump1090');
card.setConfig({entity:'sensor.a',ingress_path:'/local_fr24_dump1090'});
card.navigate('');assert.equal(events.filter(e=>typeof e==='string').at(-1),'/local_fr24_dump1090');
console.log('PASS current HA registered App routes, both instance identities, legacy saved paths, target handoff and older HA panels');

for(const slug of ['local_fr24_dump1090','e8a948e6_fr24_dump1090']) {
  card.setConfig({entity:'sensor.a',ingress_path:'/hassio/ingress/'+slug});
  card.hass={panels:{app:{component_name:'app'},[slug]:{component_name:'app',config:{addon:slug}}},states:{'sensor.a':{state:'ok',attributes:{}}}};
  for(const target of ['', 'status-page', 'settings']) {
    card.navigate(target);
    const path=events.filter(e=>typeof e==='string').at(-1);
    assert.equal(path,'/'+slug);
    assert.equal(resolvePanel(path),'/'+slug);
    if(target) {
      const pending=JSON.parse(storage.get('aircraft-bridge-navigation'));
      assert.equal(pending.path,path);
      replaced=null;
      vm.runInNewContext(code,{sessionStorage:{getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},parent:{location:{pathname:path}},location,Date});
      assert.equal(replaced,target);
    } else assert(!storage.has('aircraft-bridge-navigation'));
  }
}
console.log('PASS prefer each registered sidebar App route for all buttons; generic App fallback when sidebar is hidden');
