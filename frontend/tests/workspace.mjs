/** In-process DOM checks avoid the worker startup limit on this Windows workspace. */
import {test,afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {build} from 'esbuild';
const dom=new JSDOM('<!doctype html><html><body></body></html>',{url:'http://localhost/'});
globalThis.window=dom.window;globalThis.document=dom.window.document;
Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
globalThis.HTMLElement=dom.window.HTMLElement;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
await build({entryPoints:['src/main.tsx'],bundle:true,format:'esm',platform:'browser',jsx:'automatic',
 outfile:'.testbuild/workspace.mjs',external:['react','react-dom/client']});
const React=(await import('react')).default;
const {render,screen,fireEvent,cleanup,waitFor}=await import('@testing-library/react');
const {App,ReviewPanel}=await import('../.testbuild/workspace.mjs');
afterEach(()=>cleanup());
test('approval requires a reason and carries the exact opened version',async()=>{
 const calls=[];
 const request=async(...args)=>{calls.push(args);return {};};
 render(React.createElement(ReviewPanel,{review:{proposal_id:'p',engagement_id:'e',version_id:'v2',
  kind:'finding',status:'pending',versions:[{id:'v2',version:2,document:{title:'Late approval',wording:'Saved failure',
  severity:'medium',rationale:'Evidence',recommendation:'Correct'}}],decisions:[]},request,refresh:()=>{}}));
 const approve=screen.getByRole('button',{name:'Approve'});
 assert.equal(approve.disabled,true);
 fireEvent.change(screen.getByLabelText('Decision reason'),{target:{value:'Verified against source evidence'}});
 fireEvent.click(approve);
 await waitFor(()=>assert.deepEqual(calls,[['/reviews/p/decision','POST',
  {expected_version_id:'v2',decision:'approved',reason:'Verified against source evidence'}]]));
});
test('unauthenticated screen has no invented audit counts',()=>{
 render(React.createElement(App));
 assert.ok(screen.getByText('Your audit workspace'));
 assert.equal(screen.queryByText('Controls completed'),null);
 assert.equal(screen.getByRole('button',{name:'Open workspace'}).disabled,true);
});
test('saving wording creates a new draft with a version precondition',async()=>{
 const calls=[];
 render(React.createElement(ReviewPanel,{review:{proposal_id:'p',engagement_id:'e',version_id:'v2',
  kind:'escalation',status:'pending',versions:[{id:'v2',version:2,document:{subject:'Overdue',message:'Original'}}],decisions:[]},
  request:async(...args)=>{calls.push(args);return {};},refresh:()=>{}}));
 fireEvent.change(screen.getByLabelText('message'),{target:{value:'Reviewed wording'}});
 fireEvent.click(screen.getByRole('button',{name:'Save draft version'}));
 await waitFor(()=>assert.deepEqual(calls,[['/reviews/p/draft','POST',
  {expected_version_id:'v2',changes:{message:'Reviewed wording'}}]]));
});
