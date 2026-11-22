// Real Chromium checks. All simulated market/account responses below are test-only.
// No test fixture, generated screenshot, credential or private state is published.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {createBrotliDecompress} from 'node:zlib';
import {pipeline} from 'node:stream/promises';
import tar from 'tar-fs';
import {chromium as playwright} from 'playwright';
import chromium from '@sparticuz/chromium';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../../..');
const docs=path.join(root,'docs');
const artifacts=path.resolve(here,'../data/browser-results');
fs.mkdirSync(artifacts,{recursive:true});
// The npm-distributed browser bundles its missing NSS libraries; no CDN/apt downloads.
const libDir=path.join(artifacts,'libraries');
fs.mkdirSync(libDir,{recursive:true});
await pipeline(fs.createReadStream(path.join(here,'node_modules/@sparticuz/chromium/bin/al2023.tar.br')),createBrotliDecompress(),tar.extract(libDir));
const mime={'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.json':'application/json'};
const server=http.createServer((request,response)=>{
  try{
    const pathname=decodeURIComponent(new URL(request.url,'http://test').pathname);
    let file=path.resolve(docs,'.'+pathname);
    if(file!==docs&&!file.startsWith(docs+path.sep))throw Error('outside static tree');
    if(fs.statSync(file).isDirectory())file=path.join(file,'index.html');
    response.setHeader('Content-Type',mime[path.extname(file)]||'application/octet-stream');
    response.setHeader('Cache-Control','no-store');
    response.end(fs.readFileSync(file));
  }catch{response.writeHead(404,{'Content-Type':'application/json'});response.end('{"error":"static_only_test"}');}
});
await new Promise(resolve=>server.listen(0,'0.0.0.0',resolve));
const base=`http://127.0.0.1:${server.address().port}`;
const browser=await playwright.launch({executablePath:await chromium.executablePath(),
  args:chromium.args.filter(arg=>!['--single-process','--disable-web-security','--allow-running-insecure-content','--disable-site-isolation-trials'].includes(arg)),
  env:{...process.env,LD_LIBRARY_PATH:path.join(libDir,'lib')+':'+(process.env.LD_LIBRARY_PATH||'')},headless:true});
const reports=[];
const json=(route,value,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
const waitText=(page,id,substring)=>page.waitForFunction(({id,substring})=>document.getElementById(id)?.textContent.includes(substring),{id,substring});
async function sourceRows(page){
  const missing=await page.locator('tbody tr').evaluateAll(rows=>rows.filter(row=>![...row.querySelectorAll('a[href]')].some(a=>{
    const url=new URL(a.href);return url.protocol==='https:'&&['docs.kalshi.com','external-api.demo.kalshi.co','demo-api.kalshi.co','docs.github.com'].includes(url.hostname);
  })).map(row=>row.textContent.slice(0,100)));
  assert.deepEqual(missing,[],'Every factual table row needs an official source');
}
async function noOverflow(page){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Page must not overflow the viewport');}
async function openPage(context,url){const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));await page.goto(base+url,{waitUntil:'domcontentloaded'});return {page,errors};}
const snapshot=JSON.parse(fs.readFileSync(path.join(docs,'data/snapshot.json'),'utf8'));
try{
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  await context.route('https://**/*',route=>route.abort('internetdisconnected'));
  const {page,errors}=await openPage(context,'/');
  await waitText(page,'connection','unavailable');
  assert.ok((await page.locator('.event-child').count())>0,'Committed official snapshot should be useful offline');
  assert.match(await page.locator('#data-mode').innerText(),/observation|snapshot/i);
  assert.equal(await page.locator('#all-feed .feed-item').count(),0,'A snapshot is never an alert baseline');
  await sourceRows(page);await noOverflow(page);
  const first=await page.locator('.market-link').first().getAttribute('data-select');
  await page.locator('#search').fill(first);
  assert.equal(await page.locator('.event-child').count(),1);
  await page.locator('.market-link').click();
  assert.equal(await page.locator('#detail-sub').innerText(),first);
  await page.locator('#search').fill('');
  await page.locator('#sort').selectOption('notional');
  assert.match(await page.locator('#table-note').innerText(),/notional/i);
  await page.locator('#sort').selectOption('contracts');
  await page.locator('#show-more').click();
  assert.ok(await page.locator('.event-child').count()>16);
  for(const range of ['seconds','minutes','hours']){await page.locator(`[data-range="${range}"]`).click();assert.equal(await page.locator(`[data-range="${range}"]`).getAttribute('aria-pressed'),'true');}
  await page.locator('[data-book-side="no"]').click();
  assert.equal(await page.locator('[data-book-side="no"]').getAttribute('aria-pressed'),'true');
  await page.locator('#pause').click();assert.equal(await page.locator('#pause').getAttribute('aria-pressed'),'true');await page.locator('#pause').click();
  const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();const download=await downloadPromise;
  const exported=path.join(artifacts,'public-observations.csv');await download.saveAs(exported);
  const csv=fs.readFileSync(exported,'utf8');assert.ok(csv.includes('reported_cumulative_dollar_notional'));assert.ok(csv.includes('https://external-api.demo.kalshi.co/'));
  assert.deepEqual(errors,[]);reports.push('Desktop: search, grouped sorting, selection, chart windows, book side, pause, pagination, CSV and official row sources');
  await page.goto(base+'/',{waitUntil:'domcontentloaded'});await waitText(page,'connection','unavailable');
  await page.screenshot({path:path.join(artifacts,'dashboard-desktop.png'),fullPage:true});
  for(const topic of ['gas','elections','culture','crypto','golf']){
    await page.goto(base+'/'+topic+'/',{waitUntil:'domcontentloaded'});await waitText(page,'connection','unavailable');
    assert.equal(await page.locator('body').getAttribute('data-topic'),topic);await sourceRows(page);await noOverflow(page);
    const allowed=new Set(snapshot.events.filter(event=>event.topic===topic).flatMap(event=>event.markets.map(m=>m.ticker)));
    const tickers=await page.locator('[data-select]').evaluateAll(elements=>elements.map(e=>e.dataset.select));assert.ok(tickers.every(t=>allowed.has(t)),`Topic leakage: ${topic}`);
    reports.push(`Category ${topic}: official observations or honest empty state; source links and no overflow`);
  }
  await page.goto(base+'/portfolio/',{waitUntil:'domcontentloaded'});await page.waitForSelector('.strategy-card');
  assert.equal(await page.locator('.strategy-card').count(),2);await sourceRows(page);await noOverflow(page);
  assert.match(await page.locator('.account-note').innerText(),/No account values have been verified/);
  reports.push('Portfolio: separate hypothetical accounts, blank private values and source-linked category analysis');
  for(const url of ['/review/','/executive-summary.html']){await page.goto(base+url,{waitUntil:'domcontentloaded'});await sourceRows(page);await noOverflow(page);reports.push(`${url}: readable source-linked research tables`);}
  assert.deepEqual(errors,[]);
  await context.close();

  const mobile=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:1});
  await mobile.route('https://**/*',route=>route.abort('internetdisconnected'));
  const mobilePage=await openPage(mobile,'/');await waitText(mobilePage.page,'connection','unavailable');await noOverflow(mobilePage.page);
  await mobilePage.page.locator('#search').fill('no-such-contract');assert.equal(await mobilePage.page.locator('.event-child').count(),0);
  await mobilePage.page.locator('#search').fill('');await mobilePage.page.screenshot({path:path.join(artifacts,'dashboard-mobile.png'),fullPage:true});
  assert.deepEqual(mobilePage.errors,[]);reports.push('Mobile 390×844: responsive layout, working search and no horizontal document overflow');await mobile.close();

  // Browser-only REST simulation: deterministic fixture, never a public snapshot.
  const rest=await browser.newContext({viewport:{width:1280,height:900}});let phase=0;let privateCalls=0;
  const fixtureMarket=()=>({ticker:'SYNTHETIC-BROWSER-TEST',event_ticker:'SYNTHETIC-EVENT',title:'SYNTHETIC test contract; not a real exchange market',status:phase===2?'finalized':'active',result:phase===2?'yes':'',notional_value_dollars:'1.0000',last_price_dollars:phase?'0.50':'0.40',yes_bid_dollars:'0.48',yes_ask_dollars:'0.52',no_bid_dollars:'0.48',no_ask_dollars:'0.52',yes_bid_size_fp:'20',yes_ask_size_fp:'20',volume_fp:'100',volume_24h_fp:'10'});
  const fixtureEvent=()=>({event_ticker:'SYNTHETIC-EVENT',series_ticker:'SYNTHETIC-SERIES',title:'SYNTHETIC Bitcoin fixture, not a real event',markets:[fixtureMarket()]});
  await rest.route('**/data/snapshot.json',route=>json(route,{generated_at:null,partial:true,events:[]}));
  await rest.route('**/api/**',route=>{if(/portfolio|orders|controls/.test(route.request().url()))privateCalls++;return json(route,{error:'no_service'},404);});
  await rest.route('https://external-api.demo.kalshi.co/**',route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith('/series'))return json(route,{series:[{ticker:'SYNTHETIC-SERIES',category:'Crypto',title:'SYNTHETIC Bitcoin fixture'}]});
    if(url.pathname.endsWith('/events'))return json(route,{events:[fixtureEvent()],cursor:''});
    if(url.pathname.endsWith('/orderbook'))return json(route,{orderbook_fp:{yes_dollars:[['0.48','20']],no_dollars:[['0.48','20']]}});
    if(url.pathname.endsWith('/candlesticks'))return json(route,{candlesticks:[]});
    if(url.pathname.endsWith('/markets'))return json(route,{markets:[fixtureMarket()],cursor:''});
    return json(route,{error:'unexpected_fixture_request'},404);
  });
  const simulation=await openPage(rest,'/');await waitText(simulation.page,'connection','sampled');
  assert.equal(await simulation.page.locator('#all-feed .feed-item').count(),0);
  phase=1;await simulation.page.locator('#refresh').click();await simulation.page.waitForSelector('#all-feed .feed-item');
  assert.equal(await simulation.page.locator('#all-feed .feed-item').count(),1);assert.equal(await simulation.page.locator('#screen-feed .feed-item').count(),1);
  assert.equal(await simulation.page.locator('#paper-rows tr').count(),2);await sourceRows(simulation.page);
  phase=2;await simulation.page.locator('#refresh').click();await simulation.page.waitForFunction(()=>JSON.parse(localStorage.getItem('tradebot1-paper-v2')||'null')?.accounts?.momentum?.positions?.[0]?.status==='settled');
  const ledger=await simulation.page.evaluate(()=>JSON.parse(localStorage.getItem('tradebot1-paper-v2')));
  assert.equal(ledger.accounts.momentum.cashMicros,1_000_480_000);assert.equal(ledger.accounts.mean_reversion.cashMicros,999_480_000);
  await simulation.page.goto(base+'/portfolio/',{waitUntil:'domcontentloaded'});await waitText(simulation.page,'connection','sampled');
  assert.equal(await simulation.page.locator('#analysis-rows tr').count(),2);await sourceRows(simulation.page);
  assert.equal(privateCalls,0,'Public Pages UI must not call account or order endpoints');assert.deepEqual(simulation.errors,[]);
  reports.push('Synthetic REST integration: inclusive +10¢ alert, both feeds, two hypothetical fills, finalized settlement, persistent cash and grouped performance');await rest.close();

  // Trusted-service adapter: mocked SSE, historical points, book and paper ledger.
  const service=await browser.newContext({viewport:{width:1280,height:900}});const stamp=Date.now();
  const event={...fixtureEvent(),topic:'crypto',topic_rule:'Synthetic test-only metadata',source_url:'https://docs.kalshi.com/api-reference/events/get-event'};
  const market={...fixtureMarket(),status:'active',topic:'crypto',observed_ms:stamp,price_observed_ms:stamp,quote_observed_ms:stamp,source_url:'https://docs.kalshi.com/api-reference/market/get-market'};
  const health={mode:'demo_only',rest:'polling',websocket:'connected',data_stale:false,last_rest_success:new Date(stamp).toISOString(),last_stream_message:new Date(stamp).toISOString(),discovery_complete:true};
  const alert={id:'synthetic-server-alert',ticker:market.ticker,topic:'crypto',title:market.title,from_price:'0.6',to_price:'0.5',delta_dollars:'-0.10',timestamp_ms:stamp,selected:true,model:{strategy:'mean_reversion',outcome:'yes',gross_edge_dollars:'0.05'},source_url:market.source_url};
  const backend={health,events:[event],markets:[market],alerts:[alert],paper:{accounts:{momentum:{cash:'1000',gross_equity:'1000',positions:[]},mean_reversion:{cash:'1000',gross_equity:'1000',positions:[]}}}};
  await service.route('**/data/snapshot.json',route=>json(route,{generated_at:null,partial:true,events:[]}));
  await service.route('https://**/*',route=>route.abort('internetdisconnected'));
  await service.route('**/api/**',route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/api/health')return json(route,health);
    if(url.pathname==='/api/snapshot')return json(route,backend);
    if(url.pathname==='/api/stream')return route.fulfill({contentType:'text/event-stream',body:'event: snapshot\ndata: '+JSON.stringify(backend)+'\n\n'});
    if(url.pathname.endsWith('/history'))return json(route,{points:[{timestamp_ms:stamp-1000,price_dollars:'0.6'},{timestamp_ms:stamp,price_dollars:'0.5'}]});
    if(url.pathname.endsWith('/orderbook'))return json(route,{valid:true,stale:false,observed_ms:stamp,source_url:'https://docs.kalshi.com/api-reference/market/get-market-orderbook',yes_bids:[{price_dollars:'0.48',contracts:'20'}],no_bids:[{price_dollars:'0.48',contracts:'20'}],yes_asks:[{price_dollars:'0.52',contracts:'20'}],no_asks:[{price_dollars:'0.52',contracts:'20'}]});
    return json(route,{error:'unexpected_service_request'},404);
  });
  const adapter=await openPage(service,'/');await adapter.page.waitForSelector('#all-feed .feed-item');await adapter.page.waitForSelector('#chart path');
  assert.match(await adapter.page.locator('#all-feed').innerText(),/0\.10/);assert.match(await adapter.page.locator('#book-rows').innerText(),/0\.52/);
  assert.match(await adapter.page.locator('#chart-caption').innerText(),/Persisted demo observations/);await sourceRows(adapter.page);
  assert.deepEqual(adapter.errors,[]);reports.push('Synthetic same-origin adapter: health detection, SSE alerts, persisted chart points, actual-size book rendering and server paper separation');await service.close();
  fs.writeFileSync(path.join(artifacts,'report.json'),JSON.stringify({passed:true,checks:reports,scope:'Local Chromium; network disabled or mocked. Not authenticated Kalshi integration.'},null,2));
  console.log(reports.map((item,index)=>`PASS ${index+1}. ${item}`).join('\n'));
  console.log(`Passed ${reports.length} browser scenarios. Screenshots/report in ignored services/kalshi/data/browser-results/.`);
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
