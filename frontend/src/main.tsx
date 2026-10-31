/** Connected Phase 4 workspace: prototype styling with actual authenticated backend records. */
import React,{useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Icon} from './Icon';
import {ReviewPanel,type Review} from './ReviewPanel';
export {ReviewPanel} from './ReviewPanel';
import './style.css';
type Row=Record<string,any>;
const pages=['Overview','AI Chat','Audit Plan','Controls & Tests','Evidence Requests','Findings & Remediation','Reviews'];
const icons=['grid','chat','plan','check','mail','shield','review'];
const pretty=(v:unknown)=>JSON.stringify(v,null,2);
const area=(id:string)=>id.startsWith('PR-')?'Project governance':id.startsWith('PA-')?'Privileged access':id.startsWith('ES-')?'Endpoint security':'Audit control';
const when=(v:string)=>v?new Date(v).toLocaleString(): 'Not scheduled';
const localTime=(v:string)=>v?new Date(new Date(v).getTime()-new Date(v).getTimezoneOffset()*60000).toISOString().slice(0,16):'';
function Badge({text}:{text:string}){return <span className={'badge '+(/PASS|approved|resolved|Closed|completed/i.test(text)?'good':/FAIL|error|attention|critical/i.test(text)?'bad':'warn')}><span/>{text.replaceAll('_',' ')}</span>;}
function Info({label,value}:{label:string;value:unknown}){return <div className="info-field"><small>{label}</small><b>{typeof value==='object'?pretty(value):String(value??'Not recorded')}</b></div>;}
/** All mutations are explicit. Polling only reads; credentials remain in memory. */
export function App(){
 const [token,setToken]=useState(''),[entry,setEntry]=useState(''),[role,setRole]=useState('');
 const [page,setPage]=useState('AI Chat'),[sessions,setSessions]=useState<Row[]>([]),[sessionId,setSessionId]=useState('');
 const [datasets,setDatasets]=useState<Row[]>([]),[dataset,setDataset]=useState('');
 const [snapshot,setSnapshot]=useState<Row|null>(null),[reviews,setReviews]=useState<Review[]>([]),[artifacts,setArtifacts]=useState<Row[]>([]);
 const [panel,setPanel]=useState<{kind:string;id:string}|null>(null),[text,setText]=useState(''),[filter,setFilter]=useState('All'),[query,setQuery]=useState('');
 const [pollError,setPollError]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[revision,setRevision]=useState(0);
 const [reply,setReply]=useState(''),[deadline,setDeadline]=useState(''),[cadence,setCadence]=useState(3),[offset,setOffset]=useState(0);
 const pollKey=useRef(''); const bottom=useRef<HTMLDivElement>(null);
 const auditor=role==='auditor';
 /** Read safe backend error codes; never store credentials in browser storage. */
 async function api(path:string,method='GET',body?:unknown,credential=token):Promise<any>{
  const response=await fetch(path,{method,headers:{Authorization:'Bearer '+credential,'Content-Type':'application/json'},
   body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(typeof data.error==='string'?data.error:typeof data.detail==='string'?data.detail:'Request failed ('+response.status+')');
  return data;
 }
 function refresh(){setError('');setRevision(n=>n+1);}
 /** Do not retry a mutation automatically: backend receipts and thread IDs prevent duplicate effects. */
 async function mutate(path:string,method:string,body?:unknown,success='Saved'){
  setBusy(true);setError('');
  try{const result=await api(path,method,body);setNotice(success);refresh();return result;}
  catch(e){setError(String(e));throw e;}finally{setBusy(false);}
 }
 async function login(e:React.FormEvent){
  e.preventDefault();setBusy(true);setError('');
  try{const [me,ds]=await Promise.all([api('/workspace/me','GET',undefined,entry),api('/workspace/datasets','GET',undefined,entry)]);
   setRole(me.role);setDatasets(ds);setDataset(ds[0]?.id||'');setToken(entry);setEntry('');
  }catch(e){setError(String(e));}finally{setBusy(false);}
 }
 /** Reject stale poll responses on session switches or sign-out; no overlapping interval requests. */
 useEffect(()=>{
  if(!token)return;
  let active=true,inflight=false;
  async function load(){
   if(inflight)return;inflight=true;
   try{
    const [ss,rr]=await Promise.all([api('/workspace/sessions'),api('/reviews')]);
    if(!active)return;setSessions(ss);
    if(!sessionId){setReviews([]);setSnapshot(null);setArtifacts([]);return;}
    const snap=await api('/workspace/sessions/'+sessionId);
    if(!active)return;
    const eng=snap.context?.scope?.id;
    const key=sessionId+':'+(snap.activity.at(-1)?.id||0)+':'+eng;
    let full:Row[]|null=null;
    if(eng&&pollKey.current!==key)full=await api('/records/artifacts/'+eng);
    if(!active)return;
    setSnapshot(snap);setReviews(rr.filter((r:Review)=>r.engagement_id===eng));
    if(full){setArtifacts(full);pollKey.current=key;}
    setPollError('');
   }catch(e){if(active)setPollError(String(e));}finally{inflight=false;}
  }
  void load();const timer=setInterval(()=>void load(),2500);
  return()=>{active=false;clearInterval(timer);};
 },[token,sessionId,revision]);
 useEffect(()=>{setSnapshot(null);setArtifacts([]);setReviews([]);setPanel(null);pollKey.current='';},[sessionId]);
 useEffect(()=>{setFilter('All');setQuery('');setOffset(0);},[page]);
 useEffect(()=>{bottom.current?.scrollIntoView?.({behavior:'smooth',block:'end'});},[snapshot?.activity?.at(-1)?.id]);
 useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),5000);return()=>clearTimeout(timer);},[notice]);
 /** Each submitted assignment creates a real session; blocked work resumes through backend events. */
 async function start(e?:React.FormEvent,assignment=text){
  e?.preventDefault();if(!assignment.trim()||!auditor||busy)return;
  try{const result=await mutate('/workspace/sessions','POST',{assignment:assignment.trim(),dataset_id:dataset},'Real Grok audit queued.');
   setSessionId(result.session_id);setText('');setPage('AI Chat');}catch{}
 }
 function open(kind:string,id:string){
  setPanel({kind,id});setReply('');
  const request=snapshot?.requests?.find((r:Row)=>r.id===id);
  setDeadline(localTime(request?.followup?.due_at||''));setCadence(request?.followup?.interval_days||3);
 }
 function signOut(){setToken('');setRole('');setSessionId('');setSnapshot(null);setReviews([]);setPanel(null);setError('');}
 const context=snapshot?.context;
 const counts=snapshot?.counts||{};
 const events:Row[]=snapshot?.activity||[];
 const tasks:Row[]=(context?.work_items||[]).filter((w:Row)=>w.purpose==='audit');
 const plan=reviews.find(r=>r.kind==='plan');
 const proposals=reviews.filter(r=>r.kind==='finding');
 const pending=reviews.filter(r=>r.status==='pending').length;
 const scope=context?.scope;
 const allPop=artifacts.filter(a=>a.kind==='population');
 const catalog=useMemo(()=>{
  const map=new Map<string,Row>();
  for(const event of events)for(const c of event.details?.result?.controls||[])map.set(c.control_id,{id:c.control_id,title:c.title,requirement:c.requirement,policy_text:c.policy_text});
  for(const a of allPop)map.set(a.payload.control.id,{...map.get(a.payload.control.id),...a.payload.control,policy:a.payload.policy});
  return [...map.values()];
 },[artifacts,snapshot]);
 const selected=panel?.kind==='review'?reviews.find(r=>r.proposal_id===panel.id):undefined;
 const request=snapshot?.requests?.find((r:Row)=>r.id===panel?.id);
 const control=catalog.find(c=>c.id===panel?.id);
 const evidenceMap=new Map<string,Row>();
 for(const a of artifacts.filter(a=>a.kind==='evidence'))for(const r of a.payload.records||[])evidenceMap.set(r.id,r);
 const evidence=[...evidenceMap.values()];
 const selectedEvidence=evidenceMap.get(panel?.id||'');
 const latestRuns=(context?.latest_artifacts||[]).filter((a:Row)=>a.kind==='run');
 const currentRuns=tasks.flatMap((t:Row)=>latestRuns.filter((r:Row)=>r.run_id===t.latest_run_id));
 const resultRows=currentRuns.flatMap((r:Row)=>r.results.map((x:Row)=>({...x,control_id:r.control_id,run_id:r.run_id})));
 const total=Object.values(counts).reduce((sum:number,v)=>sum+Number(v),0);
 const pass=Number(counts.PASS||0),fail=Number(counts.FAIL||0);
 const reviewDoc=(r:Review)=>r.versions.at(-1)!.document as Row;
 /** Remediation labels are derived from persisted approvals, claims and closure records. */
 function findingState(r:Review){
  if(r.status!=='approved')return r.status;
  const finding=context?.approved_findings?.find((f:Row)=>f.proposal_id===r.proposal_id);
  if(finding?.closed)return 'Closed';
  if(reviews.some(c=>c.kind==='closure'&&reviewDoc(c).finding_id===r.proposal_id&&c.status==='pending'))return 'Closure review';
  return finding?.action_plan?'Action plan recorded':'Awaiting department action plan';
 }
 const titleOf=(r:Review)=>String(reviewDoc(r).title||reviewDoc(r).objective||reviewDoc(r).subject||r.kind+' review');
 const filteredResults=resultRows.filter((r:Row)=>(filter==='All'||r.outcome===filter||area(r.control_id)===filter)&&
  [r.entity_id,r.control_id,r.reason].join(' ').toLowerCase().includes(query.toLowerCase()));
 const filteredFindings=proposals.filter(r=>(filter==='All'||r.status===filter||reviewDoc(r).severity===filter)&&titleOf(r).toLowerCase().includes(query.toLowerCase()));
 const completed=tasks.filter(t=>t.state==='completed').length;
 const tested=tasks.filter(t=>t.latest_run_id).length;
 const reqs:Row[]=snapshot?.requests||[];
 const historicalRuns=latestRuns.filter((r:Row)=>r.purpose==='remediation');
 function exportResults(){
  const data=[['Control','Entity','Outcome','Reason'],...resultRows.map((r:Row)=>[r.control_id,r.entity_id,r.outcome,r.reason])];
  const blob=new Blob([data.map(row=>row.map((v:string)=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\n')],{type:'text/csv'});
  const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='saved-audit-results.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),500);
 }
 async function previewReply(){
  if(!request)return;setBusy(true);setError('');
  try{const preview=await api('/mail/requests/'+request.id+'/sample-reply');setReply(pretty(preview.message));setNotice(preview.notice);}
  catch(e){setError(String(e));}finally{setBusy(false);}
 }
 function manualReply(){
  const outgoing=snapshot?.communication?.find((m:Row)=>m.request_id===request.id&&m.status==='delivered');
  setReply(pretty({message_id:'manual-'+crypto.randomUUID(),in_reply_to:outgoing?.message_id||'',sender:request.document.recipient,body:'SYNTHETIC department reply',evidence:[]}));
 }
 const toolbar=(options:string[])=><div className="table-toolbar"><div className="input-search"><Icon name="search" size={17}/><input aria-label="Search records" placeholder="Search saved records..." value={query} onChange={e=>{setQuery(e.target.value);setOffset(0);}}/></div><select aria-label="Filter records" className="live-filter" value={filter} onChange={e=>{setFilter(e.target.value);setOffset(0);}}>{options.map(o=><option key={o}>{o}</option>)}</select></div>;
 const empty=(label:string)=><div className="empty-state"><Icon name="file" size={30}/><h3>{label}</h3><p>Records appear here when the real agent saves them.</p></div>;
 const heading=(eyebrow:string,title:string,desc:string)=><div className="section-title"><div><p className="overline">{eyebrow}</p><h1>{title}</h1><p className="subtext">{desc}</p></div></div>;
 if(!token)return <div className="live-login"><div className="welcome-symbol"><Icon name="shield" size={30}/></div><p className="overline">INTERNAL AUDIT MANAGER</p><h1>Your audit workspace</h1><p className="subtext">LIVE Grok agent. Saved audit records. Simulated department email.</p><form onSubmit={login}><label>Access token<input type="password" autoComplete="off" value={entry} onChange={e=>setEntry(e.target.value)} placeholder="Auditor or reviewer token from your local .env"/></label><button className="button primary" disabled={busy||!entry}>Open workspace <Icon name="arrow" size={17}/></button></form><p className="small-note">Auditors can start audits and submit synthetic replies. Both roles can review proposals. Tokens stay in memory.</p>{error&&<p role="alert" className="live-error">{error}</p>}</div>;
 return <div className={'app-shell '+(page==='AI Chat'&&panel?'split-mode':'')}><aside className="rail"><button className="logo" aria-label="Overview home" onClick={()=>setPage('Overview')}>IA</button><nav aria-label="Main navigation">{pages.map((p,i)=><button key={p} aria-label={p} title={p} className={page===p?'active':''} onClick={()=>{setPage(p);setPanel(null);}}><Icon name={icons[i]}/><span>{['Overview','AI Chat','Audit plan','Controls','Evidence','Findings','Reviews'][i]}</span>{p==='Reviews'&&pending>0&&<i>{pending}</i>}</button>)}</nav><div className="rail-bottom"><button className="avatar" title={'Signed in as '+role} onClick={()=>setNotice('Authenticated role: '+role)}>{auditor?'AU':'RV'}<span/></button><button className="text-button" onClick={signOut}>Sign out</button></div></aside>
 <div className="workspace"><header className="app-header"><div className="brand-text">Internal Audit Manager<span>/</span><b>{page}</b></div><div className="header-actions"><span className="prototype-label live-label"><span/>LIVE Grok</span><button className="icon-button" aria-label="Refresh saved records" onClick={refresh}><Icon name="reset"/></button><button className="button" onClick={()=>{setSessionId('');setPage('AI Chat');setPanel(null);}}>New audit</button></div></header>
 <div className="engagement-bar"><div><span className="engagement-dot"/><strong>{scope?.department||'Audit workspace'}</strong>{scope&&<span>{scope.period_start} - {scope.period_end}</span>}</div><div><span className="soft-tag">{role}</span><select className="session-picker" aria-label="Audit session" value={sessionId} onChange={e=>setSessionId(e.target.value)}><option value="">Choose an audit</option>{sessions.map(s=><option key={s.id} value={s.id}>{s.assignment.slice(0,65)} / {s.status}</option>)}</select>{snapshot&&<Badge text={snapshot.session.status}/>}</div></div>
 {(error||pollError)&&<div className="live-error" role="alert">{error||pollError}<button className="text-button" onClick={refresh}>Refresh</button></div>}
 <main className={page==='AI Chat'?'main-chat':'main-content'}>
 {page==='AI Chat'&&<section className="chat-canvas"><div className="chat-topline"><span><span className="status-dot"/>Internal Audit Manager</span><span className="soft-tag">Email: simulated</span></div><div className="conversation">
 {!snapshot?<div className="welcome"><div className="welcome-symbol"><Icon name="sparkle" size={34}/></div><p className="overline">YOUR CONNECTED AUDIT WORKSPACE</p><h1>From audit request<br/>to clear assurance.</h1><p>Plan the work. Follow real saved evidence.<br/>Review every important decision.</p>{sessionId?<p>Loading the selected audit...</p>:<div className="suggestions"><button disabled={!auditor||busy} onClick={()=>void start(undefined,'Audit Digital Risk from 2026-01-01 through 2026-08-31.')}><Icon name="plan"/><span>Start a Digital Risk audit<small>January - August 2026 / LIVE Grok</small></span><Icon name="up" size={16}/></button></div>}{!auditor&&<p>Reviewer access: select an existing audit to review its saved proposals. Sign in with an auditor token to start one.</p>}</div>:<>
 <div className="message user"><small>Audit assignment</small><p>{snapshot.session.assignment}</p></div>
 {events.map(ev=><div className="message assistant" key={ev.id}><div className="assistant-label"><span className="small-avatar">IA</span>Internal Audit Manager <small>{when(ev.created_at)}</small></div><p>{ev.label}</p><Badge text={ev.status}/>{ev.details?.result?.counts&&<p className="subtext">{Object.entries(ev.details.result.counts).filter(([,n])=>Number(n)>0).map(([s,n])=>n+' '+s).join(' / ')}</p>}{ev.record_id&&reviews.some(r=>r.proposal_id===ev.record_id)&&<button className="artifact-card" onClick={()=>open('review',ev.record_id)}><span className="artifact-icon"><Icon name="plan"/></span><span><b>{titleOf(reviews.find(r=>r.proposal_id===ev.record_id)!)}</b><small>Saved proposal / open for review</small></span><Icon name="up" size={17}/></button>}<details className="event-details"><summary>Saved operation details</summary><pre>{pretty(ev.details)}</pre></details></div>)}
 {['queued','running'].includes(snapshot.session.status)&&<div className="typing" role="status"><i/><i/><i/><span>{events.at(-1)?.status==='Running'?events.at(-1)?.label:'Grok is choosing its next permitted action'}...</span></div>}
 {snapshot.session.status==='attention_required'&&<div className="notice amber"><Icon name="info"/><span>Agent needs attention: {snapshot.session.error_code}. Saved results are retained.</span><button className="button" disabled={!auditor||busy} onClick={()=>void mutate('/workspace/sessions/'+sessionId+'/retry','POST',undefined,'Checkpoint queued for retry.').catch(()=>{})}>Retry saved work</button></div>}
 <div className="chat-shortcuts"><button onClick={()=>setPage('Overview')}>Audit progress</button>{plan&&<button onClick={()=>open('review',plan.proposal_id)}>Open audit plan</button>}<button onClick={()=>setPage('Reviews')}>Reviews ({pending})</button><button onClick={()=>setPage('Evidence Requests')}>Evidence requests</button></div></>}
 <div ref={bottom}/></div><form className="composer" onSubmit={e=>void start(e)}><textarea aria-label="Audit assignment" value={text} disabled={!auditor||busy} onChange={e=>setText(e.target.value)} placeholder={auditor?'Describe a new audit assignment and its exact period...':'Reviewer access / select an existing audit above'} rows={2}/><div><select aria-label="Source dataset" value={dataset} onChange={e=>setDataset(e.target.value)}>{datasets.map(d=><option key={d.id} value={d.id}>{d.description}</option>)}</select><button className="send-button" type="submit" aria-label="Start audit" disabled={!auditor||busy||!text.trim()||!dataset}><Icon name="arrow"/></button></div></form></section>}
 {page==='Overview'&&<>{heading('ENGAGEMENT OVERVIEW','A clearer view of digital risk.','Metrics come from saved backend results; approvals and closure are tracked separately.')}<div className="metrics-grid">{[['Control checks',total,'Saved item-level results'],['Confirmed failures',fail,'Historical failures retained'],['Evidence gaps',counts.MISSING_EVIDENCE||0,'Missing original evidence'],['Findings closed',snapshot?.progress?.closed_findings||0,'Human-approved closures']].map(([label,n,note])=><div className="metric-card" key={String(label)}><div className="metric-top">{label}<Icon name="check" size={18}/></div><div className="metric-number">{n}</div><small>{note}</small></div>)}</div><div className="dashboard-grid"><section className="card"><div className="card-heading"><div><h3>Control-test outcomes</h3><p>All saved current audit results</p></div><button className="text-button" onClick={exportResults}>Export CSV</button></div><div className="donut-layout"><div className="donut" style={{background:total?'conic-gradient(#008f80 0 '+pass/total*100+'%,#e6a459 '+pass/total*100+'% '+(pass+fail)/total*100+'%,#dce4e2 '+(pass+fail)/total*100+'% 100%)':'#e7eeeb'}}><div><b>{total?Math.round(pass/total*100):0}%</b><span>tests passed</span></div></div><div className="legend">{Object.entries(counts).map(([s,n])=><button key={s} onClick={()=>{setPage('Controls & Tests');setTimeout(()=>setFilter(s),0);}}><i style={{background:s==='PASS'?'#008f80':s==='FAIL'?'#e6a459':'#dce4e2'}}/>{s}<b>{String(n)}</b></button>)}</div></div></section><section className="card"><div className="card-heading"><div><h3>Execution progress</h3><p>{tested}/{tasks.length} controls tested; {completed} fully resolved</p></div><span className="percentage">{tasks.length?Math.round(tested/tasks.length*100):0}%</span></div><div className="progress-track"><span style={{width:(tasks.length?tested/tasks.length*100:0)+'%'}}/></div>{tasks.map(t=><button className="entity-row" key={t.id} onClick={()=>open('control',t.control_id)}><span>{t.control_id}</span><Badge text={t.state}/><Icon name="up" size={15}/></button>)}</section></div><div className="dashboard-grid"><section className="card"><div className="card-heading"><div><h3>Results by control area</h3><p>Click an area to inspect its saved tests</p></div></div><div className="area-bars">{[...new Set(resultRows.map((r:Row)=>area(r.control_id)))].map(a=>{const rr=resultRows.filter((r:Row)=>area(r.control_id)===a);return <button key={String(a)} onClick={()=>{setPage('Controls & Tests');setTimeout(()=>setFilter(String(a)),0);}}><div><b>{String(a)}</b><span>{rr.length} tests</span></div><div className="stack-bar"><span style={{width:rr.filter((r:Row)=>r.outcome==='PASS').length/rr.length*100+'%'}}/><span style={{width:rr.filter((r:Row)=>r.outcome==='FAIL').length/rr.length*100+'%'}}/><span className="remainder"/></div></button>;})}</div></section><section className="card"><div className="card-heading"><div><h3>Finding risk watchlist</h3><p>Risk statements from actual saved findings</p></div></div>{proposals.slice(0,5).map(r=><button className="risk-row" key={r.proposal_id} onClick={()=>open('review',r.proposal_id)}><Icon name="shield"/><span><b>{titleOf(r)}</b><small>{String(reviewDoc(r).rationale)}</small></span><Badge text={String(reviewDoc(r).severity)}/><Icon name="up" size={15}/></button>)}{!proposals.length&&empty('No findings saved yet')}</section></div></>}
 {page==='Audit Plan'&&<>{heading('AUDIT PLAN','A focused plan. A shared direction.','Review the exact saved work program. Changes create a new version.')}<section className="card plan-page">{plan?<ReviewPanel review={plan} request={api} refresh={refresh}/>:empty('The agent has not proposed a plan yet')}</section></>}
 {(page==='Reviews'||page==='Findings & Remediation')&&<>{heading(page==='Reviews'?'HUMAN OVERSIGHT':'FINDINGS & REMEDIATION',page==='Reviews'?'The right decisions. Made by you.':'From exception to resolution.','Saved proposals, complete version history and backend-enforced approvals.')}<section className="card">{toolbar(['All','pending','approved','rejected','changes_requested','high','medium','low'])}<div className="record-table-wrap"><table><thead><tr><th>Saved proposal</th><th>Kind</th><th>Status</th><th>Version</th><th/></tr></thead><tbody>{(page==='Reviews'?reviews.filter(r=>(filter==='All'||r.status===filter)&&titleOf(r).toLowerCase().includes(query.toLowerCase())):filteredFindings).map(r=><tr key={r.proposal_id} tabIndex={0} onClick={()=>open('review',r.proposal_id)} onKeyDown={e=>{if(e.key==='Enter')open('review',r.proposal_id);}}><td><b>{titleOf(r)}</b><small>{reviewDoc(r).control_id||r.proposal_id}</small></td><td>{r.kind}</td><td><Badge text={page==='Findings & Remediation'?findingState(r):r.status}/></td><td>{r.versions.at(-1)?.version}</td><td><Icon name="up" size={16}/></td></tr>)}</tbody></table></div>{!(page==='Reviews'?reviews:proposals).length&&empty('No saved proposals yet')}</section></>}
 {page==='Controls & Tests'&&<>{heading('CONTROLS & TESTS','Every control. Every source.','Actual population snapshots, deterministic outcomes and source evidence.')}<section className="card">{toolbar(['All','PASS','FAIL','MISSING_EVIDENCE','CONTRADICTORY_EVIDENCE','ERROR','Project governance','Privileged access','Endpoint security'])}<div className="record-table-wrap"><table><thead><tr><th>Control / entity</th><th>Result</th><th>Reason</th><th>Evidence</th></tr></thead><tbody>{filteredResults.slice(offset,offset+12).map((r:Row)=><tr key={r.id}><td><button className="cell-button" onClick={()=>open('control',r.control_id)}><b>{r.control_id}</b><small>{r.entity_id}</small></button></td><td><Badge text={r.outcome}/></td><td>{r.reason.replaceAll('_',' ')}</td><td>{r.evidence_ids.map((id:string)=><button className="text-button" key={id} onClick={()=>open('evidence',id)}><Icon name="file" size={14}/>Open source</button>)}</td></tr>)}</tbody></table></div><div className="pagination"><span>{filteredResults.length} saved results</span><div><button className="button small" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-12))}>Previous</button><button className="button small" disabled={offset+12>=filteredResults.length} onClick={()=>setOffset(offset+12)}>Next</button></div></div>{!resultRows.length&&empty('No control results saved yet')}</section></>}
 {page==='Evidence Requests'&&<>{heading('EVIDENCE REQUESTS','Keep the audit moving.','Simulated department email; real validation, reminders and agent resumption.')}<section className="card"><div className="card-heading"><div><h3>Department requests</h3><p>Deadline-aware reminders run while the backend server is running.</p></div></div>{reqs.map(r=><button className="request-card" key={r.id} onClick={()=>open('request',r.id)}><span className="square-icon"><Icon name="mail"/></span><div><h3>{r.document.subject}</h3><p>{r.document.recipient} / {r.document.purpose||'evidence'}</p><div className="request-tags"><Badge text={r.status}/><span>Due {when(r.followup?.due_at)}</span></div></div><Icon name="up" size={18}/></button>)}{!reqs.length&&empty('No evidence requests yet')}</section><section className="card"><h3>Saved evidence library</h3>{toolbar(['All'])}<div className="evidence-grid">{evidence.filter(e=>[e.id,e.entity_id,e.kind,e.source_id].join(' ').toLowerCase().includes(query.toLowerCase())).slice(offset,offset+12).map(e=><button className="evidence-tile" key={e.id} onClick={()=>open('evidence',e.id)}><Icon name="file" size={25}/><b>{e.kind.replaceAll('_',' ')}</b><small>{e.entity_id} / {e.source_id}</small><Badge text={e.integrity_valid?'Source fingerprint verified':'Inspect source'}/></button>)}</div><div className="pagination"><span>{evidence.length} distinct source records</span><div><button className="button small" disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-12))}>Previous</button><button className="button small" disabled={offset+12>=evidence.length} onClick={()=>setOffset(offset+12)}>Next</button></div></div></section></>}
 </main><footer className="workspace-footer"><span><span className="status-dot"/>LIVE inference / real saved records / simulated email</span><span>No automatic human approvals</span></footer></div>
 {panel&&<aside className={'detail-panel '+(page==='AI Chat'?'inline-detail':'overlay-detail')} aria-label="Record details"><div className="panel-head"><div><p className="overline">CONNECTED WORKSPACE</p><h3>{panel.kind==='review'?'Review saved proposal':panel.kind==='request'?'Evidence follow-up':'Source details'}</h3></div><button className="icon-button" aria-label="Close detail panel" onClick={()=>setPanel(null)}><Icon name="close"/></button></div><div className="panel-scroll">
 {selected&&<><ReviewPanel review={selected} request={api} refresh={refresh}/>{selected.kind==='finding'&&<div className="form-content"><h4>Department remediation</h4><div className="notice"><Icon name="mail"/><span>After finding approval, the agent requests a department action plan and implementation evidence. Use the actual simulated email threads below; closure still needs an independent saved retest.</span></div>{(context?.approved_findings||[]).filter((f:Row)=>f.proposal_id===selected.proposal_id).map((f:Row)=><div key={f.proposal_id}><Info label="Closure" value={f.closed?'Closed by approved review':'Open'}/><Info label="Department action plan" value={f.action_plan?.document||'Awaiting department reply'}/></div>)}{reqs.filter(r=>r.document.finding_id===selected.proposal_id).map(r=><button className="artifact-card" key={r.id} onClick={()=>open('request',r.id)}><Icon name="mail"/><span><b>{r.document.subject}</b><small>{r.document.purpose} / {r.status}</small></span><Icon name="up" size={16}/></button>)}{historicalRuns.filter((r:Row)=>artifacts.some(a=>a.id===r.run_id&&a.payload.finding_id===selected.proposal_id)).map((r:Row)=><details className="event-details" key={r.id}><summary>Independent retest / {r.control_id}</summary><pre>{pretty(r)}</pre></details>)}</div>}</>}
 {request&&panel.kind==='request'&&<div className="form-content"><div className="detail-hero"><span className="square-icon"><Icon name="mail"/></span><div><h2>{request.document.subject}</h2><p>{request.document.recipient}</p></div></div><Badge text={request.status}/><div className="detail-grid"><Info label="Request purpose" value={request.document.purpose||'evidence'}/><Info label="Reminders delivered/queued" value={request.followup?.reminder_count||0}/><Info label="Deadline" value={when(request.followup?.due_at)}/><Info label="Tracking" value={request.followup?.state||'Scheduling'}/></div><p className="body-copy">{request.document.message}</p><label>Deadline (your local time)<input type="datetime-local" value={deadline} onChange={e=>setDeadline(e.target.value)}/></label><label>Reminder interval (days)<input type="number" min={1} max={30} value={cadence} onChange={e=>setCadence(Number(e.target.value))}/></label><button className="button" disabled={!auditor||busy||['resolved','cancelled'].includes(request.status)||!deadline||!Number.isFinite(new Date(deadline).getTime())} onClick={()=>void mutate('/mail/requests/'+request.id+'/schedule','PATCH',{due_at:new Date(deadline).toISOString(),reminder_interval_days:cadence},'Reminder schedule updated.').catch(()=>{})}>Save schedule</button><h4>Simulated department reply</h4><div className="notice"><Icon name="info"/><span>Sample facts are synthetic and may create a real failure in this audit. Preview and edit before explicitly receiving them. No Gmail is connected.</span></div><div className="button-row"><button className="button primary" disabled={!auditor||busy||['resolved','cancelled'].includes(request.status)} onClick={()=>void previewReply()}>Prepare synthetic reply</button><button className="button" disabled={!auditor||busy} onClick={manualReply}>Write normalized reply</button></div>{reply&&<><label>Normalized reply JSON<textarea rows={14} value={reply} onChange={e=>setReply(e.target.value)}/></label><button className="button primary" disabled={!auditor||busy} onClick={async()=>{try{const payload=JSON.parse(reply);const receipt=await mutate('/mail/incoming','POST',payload,'Reply processed.');setNotice('Reply status: '+receipt.status+' / '+receipt.validation_code);}catch(e){setError(String(e));}}}>Receive simulated reply</button></>}<h4>Communication history</h4>{[...(snapshot?.communication||[]).filter((m:Row)=>m.request_id===request.id),...(snapshot?.incoming_communication||[]).filter((m:Row)=>m.request_id===request.id)].map((m:Row)=><details className="event-details" key={m.id}><summary>{m.kind||'Incoming reply'} / {m.status} / {when(m.created_at||m.received_at)}</summary><pre>{pretty(m)}</pre></details>)}</div>}
 {panel.kind==='evidence'&&<div className="form-content">{selectedEvidence?<><div className="document-preview"><div className="document-masthead"><span className="document-seal">IA</span>ORIGINAL SOURCE RECORD</div><h2>{selectedEvidence.kind.replaceAll('_',' ')}</h2><div className="detail-grid"><Info label="Entity" value={selectedEvidence.entity_id}/><Info label="Source" value={selectedEvidence.source_id}/><Info label="Observed" value={selectedEvidence.observed_on}/><Info label="Captured" value={selectedEvidence.captured_on}/><Info label="Authority" value={selectedEvidence.authority}/><Info label="Version" value={selectedEvidence.version}/></div><h4>Recorded facts</h4><pre>{pretty(selectedEvidence.facts)}</pre><Info label="Source record ID" value={selectedEvidence.source_record_id}/><Info label="Supersedes" value={selectedEvidence.supersedes_id||'Original version'}/><Badge text={selectedEvidence.integrity_valid?'Fingerprint verified':'Inspect integrity'}/></div><p className="small-note">This is a stored source record, not generated UI evidence.</p></>:empty('Source record is loading')}</div>}
 {panel.kind==='control'&&<div className="form-content"><h2>{control?.title||panel.id}</h2><h4>Policy requirement</h4><p className="body-copy">{control?.requirement}</p><p className="body-copy">{control?.policy?.text||control?.policy_text}</p>{resultRows.filter((r:Row)=>r.control_id===panel.id).map((r:Row)=><div className="entity-row" key={r.id}><span>{r.entity_id}</span><Badge text={r.outcome}/>{r.evidence_ids.map((id:string)=><button className="text-button" key={id} onClick={()=>open('evidence',id)}>Evidence <Icon name="up" size={14}/></button>)}</div>)}</div>}
 </div></aside>}
 {notice&&<div className="toast" role="status"><Icon name="check" size={18}/>{notice}<button className="icon-button" aria-label="Dismiss notification" onClick={()=>setNotice('')}><Icon name="close" size={16}/></button></div>}
 </div>;
}
if(document.getElementById('root'))createRoot(document.getElementById('root')!).render(<App/>);
