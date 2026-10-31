/** Existing version-aware Phase 4 human review, reused in the polished workspace. */
import React,{useEffect,useState} from "react";
export type Doc = Record<string, unknown>;
export type Review = {proposal_id:string; engagement_id:string; version_id:string; kind:string; status:string; versions:{id:string;version:number;document:Doc}[]; decisions:Doc[]};
const editable:Record<string,string[]> = {plan:['objective','work_program','control_ids','allow_followup_verification','verification_window_days'],
 finding:['title','wording','severity','rationale','recommendation'],escalation:['subject','message'],closure:['rationale']};
const pretty=(value:unknown)=>JSON.stringify(value,null,2);
/** Convert persisted UTC deadlines to the browser's local date-time input format. */
const localDateTime=(value:unknown)=>{if(!value)return '';const date=new Date(String(value));return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);};

/** Preserve version-aware edits and require a reason before submitting a human decision. */
export function ReviewPanel({review,request,refresh}:{review:Review;request:(path:string,method?:string,body?:unknown)=>Promise<unknown>;refresh:()=>void}) {
 const current=review.versions.at(-1)!;
 const [changes,setChanges]=useState<Doc>({});
 const [reason,setReason]=useState('');
 const [error,setError]=useState('');
 const [busy,setBusy]=useState(false);
 useEffect(()=>{setChanges({});setReason('');setError('');},[review.version_id]);
 async function submit(decision?:string) {
  setBusy(true);setError('');
  try {
   if(decision) await request('/reviews/'+review.proposal_id+'/decision','POST',{expected_version_id:review.version_id,decision,reason});
   else await request('/reviews/'+review.proposal_id+'/draft','POST',{expected_version_id:review.version_id,changes});
   refresh();
  } catch(e){setError(String(e));} finally{setBusy(false);}
 }
 return <aside className="review-panel"><p className="eyebrow">Human review ? version {current.version}</p>
  <h2>{review.kind.replaceAll('_',' ')} review</h2><span className="badge">{review.status}</span>
  <p className="muted">Approval applies to this exact saved version. Evidence and calculated results stay read only.</p>
  {(editable[review.kind]||[]).map(key=><label key={key}>{key.replaceAll('_',' ')}
   {typeof current.document[key]==='boolean' ? <input type="checkbox" checked={Boolean(changes[key]??current.document[key])}
    onChange={e=>setChanges({...changes,[key]:e.target.checked})}/> :
   <textarea rows={key==='work_program'||key==='wording'?4:2} value={String(changes[key]??(Array.isArray(current.document[key])?(current.document[key] as string[]).join(', '):current.document[key]??''))}
    onChange={e=>setChanges({...changes,[key]:key==='control_ids'?e.target.value.split(',').map(s=>s.trim()).filter(Boolean):key==='verification_window_days'?Number(e.target.value):e.target.value})}/>}
  </label>)}
  <button disabled={busy||!Object.keys(changes).length} onClick={()=>void submit()}>Save draft version</button>
  <label>Decision reason<textarea value={reason} onChange={e=>setReason(e.target.value)} placeholder="Explain your review decision"/></label>
  <div className="actions">{['approved','changes_requested','rejected'].map(d=><button key={d} disabled={busy||!reason.trim()||review.status!=='pending'}
    onClick={()=>void submit(d)}>{d==='approved'?'Approve':d==='rejected'?'Reject':'Request changes'}</button>)}</div>
  {error&&<p role="alert">{error}</p>}
  <details><summary>Source document and review history</summary><pre>{pretty({document:current.document,versions:review.versions,decisions:review.decisions})}</pre></details>
 </aside>;
}

