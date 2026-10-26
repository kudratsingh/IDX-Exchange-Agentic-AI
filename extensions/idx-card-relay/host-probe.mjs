// Offline host-path counterexample. No gateway connection or provider invocation.
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import plugin from './relay.ts';

// Test-only host internals: never imported by the runtime candidate.
// This compatibility probe is pinned to the inspected installed distribution.
const flag=process.argv.indexOf('--host-root');
if(flag<0 || !process.argv[flag+1]) throw Error('Supply --host-root for OpenClaw 2026.9.5.');
const host=resolve(process.argv[flag+1]);
assert.equal(JSON.parse(readFileSync(join(host,'package.json'),'utf8')).version,'2026.9.5');
const fixture=mkdtempSync(join(tmpdir(),'idx-relay-host-probe-'));
process.env.OPENCLAW_STATE_DIR=join(fixture,'state');
process.env.OPENCLAW_CONFIG_PATH=join(fixture,'config.json');
writeFileSync(process.env.OPENCLAW_CONFIG_PATH,'{}',{mode:0o600});
const {createAgentEventHandler,createChatRunState,createSessionEventSubscriberRegistry,
 createSessionMessageSubscriberRegistry}=await import(pathToFileURL(join(host,'dist/server-chat-Bchd-0vr.mjs')).href);
const {i:initializeGlobalHookRunner,t:getGlobalHookRunner}=await import(pathToFileURL(join(host,'dist/hook-runner-global-CN2-D2Rq.mjs')).href);
const hooks=[];
let outgoingInvocations=0;
plugin.register({on(hookName,handler){hooks.push({pluginId:'idx-card-relay',hookName,handler:(...args)=>{if(hookName==='reply_payload_sending')outgoingInvocations++;return handler(...args);}})}});
initializeGlobalHookRunner({plugins:[],hooks:[],typedHooks:hooks});
const runner=getGlobalHookRunner();
assert.equal(runner.hasHooks('reply_payload_sending'),true);
const identity={agentId:'idx',sessionKey:'agent:idx:synthetic',runId:'offline-run'};
const original='Synthetic draft\n2 beds · 2 baths · 960 sqft\nNothing has been sent.';
await runner.runAfterToolCall({toolName:'idx__draft_email',toolCallId:'call_one',runId:identity.runId,result:{ok:true,data:{state:'pending',body:original},message:original}},identity);
const frames=[];
const state=createChatRunState();
const handler=createAgentEventHandler({
 broadcast:(event,payload)=>frames.push({event,payload}),broadcastToConnIds:()=>{},
 nodeSendToSession:()=>{},nodeHasSessionSubscribers:()=>false,agentRunSeq:new Map(),chatRunState:state,
 resolveSessionKeyForRun:()=>identity.sessionKey,clearAgentRunContext:()=>{},toolEventRecipients:state.toolEventRecipients,
 sessionEventSubscribers:createSessionEventSubscriberRegistry(()=>false),
 sessionMessageSubscribers:createSessionMessageSubscriberRegistry(()=>false),
 loadGatewaySessionLifecycleSnapshotForEvent:()=>({row:null}),persistGatewaySessionLifecycleEventForEvent:()=>{throw Error('Persistence forbidden in offline probe');},
});
const bad=original.replace('960 sqft','1,240 sqft');
handler({runId:identity.runId,sessionKey:identity.sessionKey,agentId:'idx',seq:1,ts:Date.now(),stream:'assistant',
 projectSessionLifecycle:false,projectSessionMessages:false,data:{text:bad}});
await new Promise(resolve=>setTimeout(resolve,30));
const browser=frames.filter(x=>x.event==='chat').map(x=>x.payload.message?.content?.filter(x=>x.type==='text').map(x=>x.text).join('')??'');
assert.ok(browser.some(text=>text.includes('1,240 sqft')));
assert.equal(outgoingInvocations,0);
const whatsapp=await runner.runReplyPayloadSending({payload:{text:'Here is your preview.\n[[IDX_CARD:call_one]]'},kind:'final',channel:'whatsapp',sessionKey:identity.sessionKey,runId:identity.runId},{channelId:'whatsapp',sessionKey:identity.sessionKey,runId:identity.runId});
assert.equal(outgoingInvocations,1);
assert.equal(whatsapp.payload.text,'Here is your preview.\n'+original);
console.log(JSON.stringify({host_version:'2026.9.5',host_hooks_registered:2,whatsapp_stub_byte_identity:true,browser_live_text_protected:false,browser_outgoing_hook_invocations:0,model_rewrite_visible_in_browser:true}));
handler.dispose();
state.clearRun(identity.runId);
