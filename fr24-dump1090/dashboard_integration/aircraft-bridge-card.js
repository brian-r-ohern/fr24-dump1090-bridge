/* Aircraft Bridge dashboard card v0.6.9.3 — status comes from an HA status entity. */
class AircraftBridgeCard extends HTMLElement {
  setConfig(config) {
    if (config.ingress_path && (!config.ingress_path.startsWith('/') || config.ingress_path.startsWith('//')))
      throw new Error('Ingress path must be a local path');
    this.config = {...config}; this.render();
  }
  set hass(hass) { this._hass = hass; this.render(); }
  getCardSize() { return 5; }
  static getConfigElement() { return document.createElement('aircraft-bridge-card-editor'); }
  static getStubConfig(hass) {
    const entity=Object.keys(hass?.states||{}).find(id=>hass.states[id].attributes?.aircraft_bridge);
    return {entity:entity||'',title:''};
  }
  render() {
    if (!this.config || !this._hass) return;
    if (!this.shadowRoot) this.attachShadow({mode:'open'});
    const state=this._hass.states[this.config.entity], s=state?.attributes || {};
    const unavailable=!state || ['unavailable','unknown'].includes(state.state);
    const e=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const sourceLabels={sbs_30003:'SBS → dump1090',flights_js:'FR24 HTTP → dump1090',aircraft_json:'ADSB JSON → dump1090',swim_tfms:'FAA TFMS → dump1090'};
    const consumers=s.feed_consumers || {}, age=s.last_message_age_seconds??s.last_poll_age_seconds;
    const feedStatus=s.feed_status??state?.state;
    const sourceNames={sbs_30003:'SBS',flights_js:'FR24 HTTP',aircraft_json:'ADSB JSON',swim_tfms:'TFMS'};
    const open=this.shadowRoot.querySelector('details')?.open || false;
    this.shadowRoot.innerHTML=`<style>
    ha-card{padding:18px;color:var(--primary-text-color)}header{display:flex;gap:12px;align-items:center}ha-icon{color:var(--primary-color)}h2{margin:0;font-size:21px;font-weight:500}.sub{font-size:13px;color:var(--secondary-text-color);margin-top:5px}table{width:100%;border-collapse:collapse;margin-top:12px}td{padding:6px 0;border-bottom:1px solid var(--divider-color)}td:last-child{text-align:right}nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}button{color:var(--primary-color);background:none;border:1px solid var(--divider-color);border-radius:6px;padding:8px;cursor:pointer}details{margin-top:12px}summary{cursor:pointer}p{font-size:13px;color:var(--secondary-text-color)}.ok{color:var(--success-color,#43a047)}.bad{color:var(--error-color,#db4437)}
    </style><ha-card><header><ha-icon icon="mdi:radar"></ha-icon><div><h2>${e(this.config.title||('Aircraft Bridge'+(sourceNames[s.source]?' · '+sourceNames[s.source]:'')))}</h2><div class="sub">${e(sourceLabels[s.source]||s.source)} · Version ${e(s.build_version)}</div></div></header>
    <table><tr><td>Feed status</td><td class="${!unavailable&&String(feedStatus).toLowerCase()==='ok'?'ok':'bad'}">${e(unavailable?'Unavailable':feedStatus)}</td></tr>
    <tr><td>Receiver</td><td>${e(unavailable?'—':s.receiver)}</td></tr><tr><td>Aircraft / positioned</td><td>${e(unavailable?'—':s.aircraft_total)} / ${e(unavailable?'—':s.aircraft_with_position)}</td></tr>
    <tr><td>Last update age</td><td>${e(unavailable?'—':age)} sec</td></tr>
    <tr><td>Recent external client groups</td><td>${e(unavailable?'—':consumers.external_count)}${consumers.count_is_estimate?' (estimate)':''}</td></tr></table>
    <details ${open?'open':''}><summary>Diagnostics and dependencies</summary><table>
    ${s.message_rate_per_second==null?'':`<tr><td>Message rate</td><td>${e(s.message_rate_per_second)} / sec</td></tr>`}<tr><td>Uptime</td><td>${e(s.uptime_seconds)} sec</td></tr><tr><td>Parse errors</td><td>${e(s.parse_errors)}</td></tr><tr><td>HTTP requests</td><td>${e(s.requests_served)}</td></tr><tr><td>Built-in map client groups</td><td>${e(consumers.internal_count)}</td></tr></table>
    <ul>${(consumers.clients||[]).map(c=>`<li>${e(c.label)} · ${e(c.last_seen_age_seconds)} sec ago · ${e(c.identification)}</li>`).join('') || '<li>No recent feed requests.</li>'}</ul>
    <p>Stopping or uninstalling this Bridge interrupts dependent applications. ${e(consumers.window_seconds||60)}-second activity window; unidentified groups may combine multiple apps. Zero recent clients does not establish that no apps depend on this Bridge.</p></details>
    <nav><button type="button" data-page="">Open map</button><button type="button" data-page="status-page">Status</button><button type="button" data-page="settings">Settings recovery</button></nav><p id="error" role="status">${unavailable?'Status entity unavailable; check the status entity and App.':''}</p></ha-card>`;
    for(const button of this.shadowRoot.querySelectorAll('button')) button.onclick=()=>this.navigate(button.dataset.page);
  }
  navigate(target) {
    try {
      let path=this.config.ingress_path||this._hass.states[this.config.entity]?.attributes?.ingress_path;
      if(!path || !path.startsWith('/') || path.startsWith('//')) throw new Error('Choose a Bridge status entity or configure its Ingress path');
      // HA now registers the generic App panel at /app/<slug>. Convert old
      // saved card paths too, using registered panels for older HA versions.
      const app=path.match(/^\/(?:hassio\/ingress|app)\/([a-z0-9_]+)\/?$/);
      if(app) {
        const panels=this._hass.panels||{};
        const slug=app[1], dedicated=panels[slug];
        path=dedicated && (dedicated.component_name==='app' || dedicated.config?.addon===slug)
          ? '/'+slug
          : (panels.app || !panels.hassio ? '/app/' : '/hassio/ingress/')+slug;
      }
      if(target) sessionStorage.setItem('aircraft-bridge-navigation',JSON.stringify({path,target,at:Date.now()}));
      else sessionStorage.removeItem('aircraft-bridge-navigation');
      history.pushState({from:window.location.pathname+window.location.search},'',path);
      window.dispatchEvent(new CustomEvent('location-changed',{detail:{replace:false}}));
    } catch(e) { this.shadowRoot.getElementById('error').textContent='Navigation failed: '+e.message; }
  }
}
const previous=customElements.get('aircraft-bridge-card');
if(!previous) customElements.define('aircraft-bridge-card',AircraftBridgeCard);
else { // Upgrade an already loaded 0.6.9 resource without redefining the element.
  for(const key of Object.getOwnPropertyNames(AircraftBridgeCard.prototype))
    if(key!=='constructor') Object.defineProperty(previous.prototype,key,Object.getOwnPropertyDescriptor(AircraftBridgeCard.prototype,key));
  for(const key of ['getConfigElement','getStubConfig']) previous[key]=AircraftBridgeCard[key];
}
window.customCards=window.customCards||[];
if(!window.customCards.some(c=>c.type==='aircraft-bridge-card')) window.customCards.push({type:'aircraft-bridge-card',name:'Aircraft Bridge',description:'Bridge feed status and recent feed dependencies',preview:false});

class AircraftBridgeCardEditor extends HTMLElement {
  setConfig(config) { this.config={...config}; this.render(); }
  set hass(hass) { this._hass=hass; this.render(); }
  render() {
    if(!this.config||!this._hass) return;
    if(!this.shadowRoot) this.attachShadow({mode:'open'});
    const e=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const choices=Object.keys(this._hass.states).filter(id=>id.startsWith('sensor.')&&(this._hass.states[id].attributes?.aircraft_bridge||this._hass.states[id].attributes?.build_version));
    this.shadowRoot.innerHTML=`<style>label{display:block;margin:12px 0}select,input{box-sizing:border-box;width:100%;padding:10px;color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:6px}small{color:var(--secondary-text-color)}</style>
    <label>Bridge status entity<select id="entity"><option value="">Select a Bridge</option>${choices.map(id=>`<option value="${e(id)}" ${id===this.config.entity?'selected':''}>${e(this._hass.states[id].attributes.friendly_name||id)}</option>`).join('')}</select></label>
    <label>Title (optional)<input id="title" value="${e(this.config.title)}" placeholder="Automatic title from feed type"></label>
    <small>Map and status links use this instance’s Home Assistant Ingress page.</small>`;
    for(const key of ['entity','title']) this.shadowRoot.getElementById(key).onchange=event=>{
      this.config={...this.config,[key]:event.target.value};
      this.dispatchEvent(new CustomEvent('config-changed',{detail:{config:this.config},bubbles:true,composed:true}));
    };
  }
}
if(!customElements.get('aircraft-bridge-card-editor')) customElements.define('aircraft-bridge-card-editor',AircraftBridgeCardEditor);
