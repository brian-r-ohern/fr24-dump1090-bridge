/* Layout regression harness. Supply an HTML file extracted from MAP_HTML.
 * Uses actual overlay HTML/CSS/layout script, sample status text, and a zoom-control
 * size fixture. Does not simulate Leaflet data collection or network activity.
 * node tools/check_map_layout.cjs /tmp/bridge-map.html [screenshot-directory]
 * Requires Playwright and its Chromium browser in the local development environment.
 */
const fs=require('fs'),path=require('path'),assert=require('assert'),{chromium}=require('playwright');
const source=fs.readFileSync(process.argv[2],'utf8');
const html=source.replace(/__SOURCE_TITLE__/g,'FAA TFMS → dump1090').replace(/<link\b[^>]*>/g,'').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,s=>s.includes('id="overlay-layout"')?s:'').replace('<div id="map"></div>','<div id="map"></div><div class="leaflet-control-zoom" style="position:absolute;left:10px;top:10px;width:32px;height:64px;background:white;z-index:800">+<br>−</div>');
const rows=[['Build','0.6.4'],['Feed','OK'],['Source','sbs_30003'],['Receiver','connected'],['Messages','3,100,535'],['Message rate','309.8 / sec'],['Aircraft','89'],['With position','76'],['Without position','13'],['Max range','258.6 NM'],['Parse errors','0'],['Reconnects','0'],['Tracker','Awaiting detection'],['O/D airport','SYR'],['Uptime','2h 29m']];
async function fill(page,track){await page.evaluate(({rows,track})=>{document.getElementById('info-grid').innerHTML=rows.map(([k,v])=>'<span>'+k+'</span><span>'+v+'</span>').join('');document.getElementById('stats').textContent='OK · 76 positioned / 89 total · 309.8 msg/sec';document.getElementById('density-state').textContent='30 days · blue → red';document.getElementById('trackbox').style.display=track?'block':'none';}, {rows,track});await page.waitForTimeout(100);}
async function check(page){
 const boxes=await page.evaluate(()=>Object.fromEntries(['.topbar','.info','#trackbox','.leaflet-control-zoom'].map(selector=>{const e=document.querySelector(selector),r=e.getBoundingClientRect();return[selector,{x:r.x,y:r.y,w:r.width,h:r.height}]})));
 const overlaps=(a,b)=>a.w>0&&b.w>0&&a.h>0&&b.h>0&&a.x<b.x+b.w-.5&&b.x<a.x+a.w-.5&&a.y<b.y+b.h-.5&&b.y<a.y+a.h-.5;
 for(const [a,b] of [['.info','.topbar'],['.info','#trackbox'],['.topbar','.leaflet-control-zoom'],['#trackbox','.topbar']])assert(!overlaps(boxes[a],boxes[b]),'Overlap '+a+' '+b+': '+JSON.stringify(boxes));
 const size=page.viewportSize();for(const [selector,box] of Object.entries(boxes)){if(box.h===0)continue;assert(box.x>=-.5&&box.y>=-.5&&box.x+box.w<=size.width+.5&&box.y+box.h<=size.height+.5,'Outside viewport '+selector+': '+JSON.stringify(box));}
 const summary=await page.locator('.info-title').boundingBox();assert(summary);assert.equal(await page.evaluate(({x,y})=>document.elementFromPoint(x,y).closest('summary')!==null,{x:summary.x+summary.width/2,y:summary.y+summary.height/2}),true,'Status heading must be tappable');
}
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage();
 for(const [width,height] of [[393,650],[760,300],[844,330],[320,480],[1280,720]]){
  await page.setViewportSize({width,height});await page.setContent(html);await fill(page,true);
  const compact=width<=900||height<=600;assert.equal(await page.locator('#bridge-info').evaluate(e=>e.open),!compact);
  await check(page);
  if(compact){await page.locator('.info-title').click();await page.waitForTimeout(100);await check(page);}
  await page.evaluate(()=>{document.getElementById('density-options').hidden=false;document.getElementById('density-options').open=true;document.getElementById('envelope-control').open=true});await page.waitForTimeout(100);await check(page);
  await page.evaluate(()=>{document.getElementById('density-options').hidden=true;document.getElementById('envelope-control').open=false});await page.waitForTimeout(100);await check(page);
  await fill(page,false);await check(page);await fill(page,true);await check(page);
  if(process.argv[3]){fs.mkdirSync(process.argv[3],{recursive:true});await page.screenshot({path:path.join(process.argv[3],`map-layout-${width}x${height}.png`)});}
  console.log(`PASS ${width}x${height}: collapsed/expanded status and track visibility`);
 }
 // Rotate an expanded phone layout without recreating the page.
 await page.setViewportSize({width:393,height:650});await page.setContent(html);await fill(page,true);await page.locator('.info-title').click();await page.waitForTimeout(100);
 await page.setViewportSize({width:844,height:300});await page.waitForTimeout(100);await check(page);
 await page.setViewportSize({width:393,height:650});await page.waitForTimeout(100);await check(page);
 console.log('PASS orientation changes with expanded status');
 await page.keyboard.press('Tab');await page.locator('.info-title').focus();const before=await page.locator('#bridge-info').evaluate(e=>e.open);await page.keyboard.press('Enter');assert.equal(await page.locator('#bridge-info').evaluate(e=>e.open),!before);console.log('PASS keyboard status toggle');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
