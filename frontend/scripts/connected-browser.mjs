/** Real connected UI integration check against the isolated server on port 8001. */
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const root=new URL('../',import.meta.url);
const targets=await(await fetch('http://127.0.0.1:9224/json')).json();
const socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise((r,j)=>{socket.addEventListener('open',r,{once:true});socket.addEventListener('error',j,{once:true});});
let id=0;const pending=new Map();const errors=[];const milestones=[];
socket.addEventListener('message',e=>{const d=JSON.parse(e.data);if(d.id){const p=pending.get(d.id);if(p){pending.delete(d.id);d.error?p.reject(Error(d.error.message)):p.resolve(d.result);}}
 if(d.method==='Runtime.exceptionThrown')errors.push(d.params.exceptionDetails.text);
});
function cdp(method,params={}){return new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});socket.send(JSON.stringify({id:n,method,params}));});}
async function run(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.text);return r.result.value;}
async function wait(expression,seconds=180){for(let n=0;n<seconds*2;n++){if(await run(expression))return;await new Promise(r=>setTimeout(r,500));}throw Error('Timed out: '+expression);}
async function click(text){await run('(()=>{const b=[...document.querySelectorAll("button")].find(b=>b.textContent.trim()==='+JSON.stringify(text)+');if(!b)throw Error("Missing button: '+text+'");b.click()})()');}
async function nav(name){await run('document.querySelector("button[aria-label=\\"'+name+'\\"]").click()');}
async function screenshot(name){await new Promise(r=>setTimeout(r,350));const r=await cdp('Page.captureScreenshot',{format:'png'});await fs.writeFile(new URL('review/'+name+'.png',root),Buffer.from(r.data,'base64'));}
function done(label){milestones.push(label);console.log(label);}
async function approve(){await wait('!!document.querySelector(".review-panel")');await run('document.querySelector(".review-panel label:last-of-type textarea").focus()');await cdp('Input.insertText',{text:'Explicit UI evaluation-human review of the saved source records.'});await click('Approve');}
async function reply(){await wait('[...document.querySelectorAll(".panel-scroll .badge")].some(b=>b.textContent.trim()==="sent")');
 await click('Prepare synthetic reply');await wait('!!document.querySelector(".panel-scroll textarea[rows=\\"14\\"]")');await click('Receive simulated reply');await wait('[...document.querySelectorAll(".panel-scroll .badge")].some(b=>b.textContent.trim()==="resolved")');}
try{
 await fs.mkdir(new URL('review/',root),{recursive:true});
 await cdp('Page.enable');await cdp('Runtime.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:'http://127.0.0.1:8001/'});
 await wait('!!document.querySelector("input[type=password]")');
 await run('document.querySelector("input[type=password]").focus()');await cdp('Input.insertText',{text:'ui-test-auditor'});await click('Open workspace');
 await wait('!!document.querySelector(".composer")');done('Authenticated connected workspace');
 await run('[...document.querySelectorAll(".suggestions button")][0].click()');
 await wait('!!document.querySelector(".artifact-card")');await run('document.querySelector(".artifact-card").click()');
 await screenshot('connected-01-plan');await approve();done('Real Grok plan reviewed and approved in UI');
 await nav('Evidence Requests');await wait('!!document.querySelector(".request-card")');
 await run('document.querySelector(".request-card").click()');await reply();done('Synthetic original evidence received through real validation');
 await nav('Findings & Remediation');await wait('!!document.querySelector("tbody tr")');
 const finding=await run('document.querySelector("tbody tr td b").textContent');
 await run('document.querySelector("tbody tr").click()');await approve();done('Real saved finding reviewed and approved');
 async function openFinding(){await nav('Findings & Remediation');await wait('!!document.querySelector("tbody tr")');await run('[...document.querySelectorAll("tbody tr")].find(r=>r.textContent.includes('+JSON.stringify(finding)+')).click()');}
 await openFinding();await wait('[...document.querySelectorAll(".panel-scroll .artifact-card")].some(b=>b.textContent.includes("action_plan"))');
 await run('[...document.querySelectorAll(".panel-scroll .artifact-card")].find(b=>b.textContent.includes("action_plan")).click()');await reply();done('Department action plan submitted through real email workflow');
 await openFinding();await wait('[...document.querySelectorAll(".panel-scroll .artifact-card")].some(b=>b.textContent.includes("implementation"))');
 await run('[...document.querySelectorAll(".panel-scroll .artifact-card")].find(b=>b.textContent.includes("implementation")).click()');await reply();done('Synthetic implementation evidence submitted');
 await nav('Reviews');await wait('[...document.querySelectorAll("tbody tr")].some(r=>r.children[1]?.textContent==="closure")',240);
 await run('[...document.querySelectorAll("tbody tr")].find(r=>r.children[1]?.textContent==="closure").click()');
 await approve();done('Independent Grok retest and human closure approval completed');
 await nav('Overview');await wait('!!document.querySelector(".donut")');await screenshot('connected-02-overview');
 await nav('AI Chat');await screenshot('connected-03-activity');
 await cdp('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await screenshot('connected-04-mobile');
 assert.equal(await run('document.documentElement.scrollWidth>window.innerWidth+1'),false);
 assert.deepEqual(errors,[]);
 const report={status:'PASS',date:new Date().toISOString(),inference:'Real Azure Grok',email:'Simulated; actual validation and resumption',milestones,jsErrors:errors,scope:'Isolated PR-02 development workflow; user database untouched'};
 await fs.writeFile(new URL('review/connected-browser.json',root),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}catch(e){await fs.writeFile(new URL('review/connected-browser.json',root),JSON.stringify({status:'FAIL',error:String(e),milestones,jsErrors:errors},null,2));throw e;}
finally{socket.close();}
