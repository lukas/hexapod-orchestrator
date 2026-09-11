'use strict';
const $=id=>document.getElementById(id);
const money=value=>value===null||value===undefined?'Unknown':new Intl.NumberFormat(undefined,{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:Number(value)>0&&Number(value)<.01?6:2}).format(Number(value));
const when=value=>value?new Date(value).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'—';
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;};
let loadVersion=0;
async function api(path,options={}){const r=await fetch(path,{...options,credentials:'same-origin',headers:{'Accept':'application/json',...(options.headers||{})}});if(r.status===401){$('signin').hidden=false;$('dashboard').hidden=true;throw new Error('Sign in to view private records.');}if(!r.ok)throw new Error(`Unable to load records (${r.status}).`);return r.json();}
function paragraph(parent,text,cls){if(text)parent.append(node('p',text,cls));}
function action(parent,a){const box=node('article',undefined,'recommendation');box.append(node('strong',`${(a.action||a.code||'Recommendation').replaceAll('_',' ')} · ${a.target||a.subject||'Project'}`));paragraph(box,a.reason||a.detail);paragraph(box,a.proposed_action);if(a.evidence?.length){const d=node('details');d.append(node('summary','Evidence'));const ul=node('ul',undefined,'muted');for(const e of a.evidence)ul.append(node('li',typeof e==='string'?e:JSON.stringify(e)));d.append(ul);box.append(d);}parent.append(box);}
function strategy(parent,assessment){if(!assessment)return;const section=node('div',undefined,'goals');for(const [id,title]of [['robot_lab_throughput','Robot Lab throughput'],['rl_experiment_portfolio','RL experiment portfolio'],['integrated_policy','Integrated stand-and-walk policy']]){const topic=assessment[id];if(!topic)continue;const card=node('article',undefined,'goal');card.append(node('strong',title));paragraph(card,topic.diagnosis);paragraph(card,'Decision: '+(topic.decision||'Unknown'));paragraph(card,'Review again: '+(topic.next_review_trigger||'New evidence'),'muted');if(topic.evidence?.length){const details=node('details');details.append(node('summary','Evidence'));const list=node('ul',undefined,'muted');for(const item of topic.evidence)list.append(node('li',item));details.append(list);card.append(details);}section.append(card);}if(section.childElementCount)parent.append(section);}
function attempts(parent,data){const prior=data.report?.prior_attempts||[],reservations=data.reservations||[];if(!prior.length&&!reservations.length)return;const d=node('details');d.append(node('summary','Review attempts and cost reservations'));for(const item of prior){const llm=item.llm_review||{};paragraph(d,`${when(item.generated_at)} · ${llm.model||llm.provider||'Review'} · ${item.outcome||llm.status||'Unknown'}`);if(llm.error)paragraph(d,llm.error,'risks');}for(const cost of reservations){paragraph(d,`${when(cost.created_at)} · ${cost.status==='pending'?'Usage unknown; '+money(cost.reserved_usd)+' remains reserved':'Recorded cost: '+money(cost.actual_usd)}`,'muted');}paragraph(d,'All attempts share this run’s original spending limit. Pending reservations are not confirmed charges.','muted');parent.append(d);}
function correctionNotices(parent,corrections){
  for(const correction of corrections||[]){
    const notice=node('aside',undefined,'correction-notice');
    notice.append(node('strong','Owner correction to this review'));
    paragraph(notice,correction.lesson);
    paragraph(notice,`${when(correction.recorded_at)} · ${correction.owner||'Owner'} · ${correction.source||'Recorded correction'}`,'muted');
    if(correction.evidence?.length){const list=node('ul',undefined,'muted');for(const item of correction.evidence)list.append(node('li',item));notice.append(list);}
    paragraph(notice,'The original model report below is preserved as historical evidence.','muted');
    parent.append(notice);
  }
}
function review(parent,data){parent.replaceChildren();correctionNotices(parent,data.corrections);const r=data.report;const run=data.run||{};paragraph(parent,`${when(run.started_at)} · ${run.provider||r?.llm_review?.provider||'Deterministic'}${r?.llm_review?.model?' / '+r.llm_review.model:''}`,'muted');if(!r){paragraph(parent,'This run has no saved review report. Inspect its status and cost reservations before retrying.');return;}const llm=r.llm_review||{},assessment=llm.review;paragraph(parent,assessment?.summary||'This run contains a deterministic review of project activity.');if(llm.error)paragraph(parent,llm.error,'risks');if(llm.validation_error)paragraph(parent,llm.validation_error,'muted');if(llm.invalid_advisory_excerpt){const invalid=node('details');invalid.append(node('summary','Unvalidated model response'));invalid.append(node('pre',llm.invalid_advisory_excerpt,'muted'));parent.append(invalid);}strategy(parent,assessment?.strategic_assessment);const actions=assessment?.recommended_actions||r.findings||[];for(const a of actions)action(parent,a);if(!actions.length)paragraph(parent,'No action recommended. Wait for new evidence or spending.','muted');if(assessment?.risks?.length){const list=node('ul',undefined,'risks');for(const risk of assessment.risks)list.append(node('li',risk));parent.append(list);}if(assessment?.goal_assessment){const goals=node('div',undefined,'goals');for(const [id,title]of [['any_means','Walking by any effective means'],['rl_only','Walking learned only through RL']]){const goal=assessment.goal_assessment[id];if(!goal)continue;const el=node('article',undefined,'goal');el.append(node('strong',title));for(const [key,label]of [['sim','Simulation'],['physical','Physical robot'],['next_step','Next step']])paragraph(el,`${label}: ${goal[key]||'Unknown'}`);goals.append(el);}parent.append(goals);}if(r.source_errors?.length){const d=node('details');d.append(node('summary',`Source coverage (${r.source_errors.length} issues)`));for(const e of r.source_errors)paragraph(d,typeof e==='string'?e:(e.message||JSON.stringify(e)),'muted');parent.append(d);}attempts(parent,data);paragraph(parent,`Actual cost: ${money(run.actual_cost_usd)} · Reserved: ${money(run.pending_reserved_usd)}`,'muted');}
async function showRun(id){$('run-detail').replaceChildren(node('p','Loading review…'));$('run-dialog').showModal();try{review($('run-detail'),await api('/api/runs/'+encodeURIComponent(id)));}catch(e){$('run-detail').replaceChildren(node('p',e.message));}}

function renderSchedule(status){
  const schedule=status.scheduler||{};
  const enabled=schedule.enabled;
  const configured=Boolean(schedule.configured_at);
  const title=enabled===true?'Scheduling enabled':enabled===false?(configured?'Scheduling disabled':'Schedule not configured'):'Schedule unavailable';
  $('schedule-badge').textContent=title;
  $('schedule-summary').textContent=title;
  const checkMinutes=Number(schedule.check_interval_seconds)/60;
  const reviewHours=Number(schedule.review_interval_seconds)/3600;
  $('schedule-interval').textContent=checkMinutes&&reviewHours?`Free gates every ${checkMinutes} min · active-work reviews after ${reviewHours} h`:'No interval recorded';
  $('next-check').textContent=schedule.next_check_at?when(schedule.next_check_at):(enabled?'Not recorded':'Not scheduled');
  $('last-check').textContent=schedule.last_check_at?when(schedule.last_check_at):'No check recorded';
  $('last-check-outcome').textContent=schedule.last_outcome?String(schedule.last_outcome).replaceAll('_',' '):'No outcome recorded';
  $('free-idle-checks').textContent=schedule.free_checks===undefined?'Unknown':String(schedule.free_checks);
  const detail=$('schedule-detail');detail.replaceChildren();
  if(schedule.review_hold)paragraph(detail,'Paid reviews are held: '+schedule.review_hold,'risks');
  paragraph(detail,schedule.last_detail);
  const lastCheck=Date.parse(schedule.last_check_at);
  if(enabled&&(!Number.isFinite(lastCheck)||Date.now()-lastCheck>(Number(schedule.check_interval_seconds)||300)*2000+60000)){
    paragraph(detail,'The schedule is enabled, but there is no recent runner check. Recorded settings alone do not establish that the runner is healthy.','risks');
  }
  if(schedule.active_check)paragraph(detail,`A gate check was recorded as active at ${when(schedule.active_check_started_at)}. This does not by itself indicate a paid review.`);
  for(const warning of schedule.limitations||[])paragraph(detail,warning);
  const active=$('active-wake');active.replaceChildren();
  if(status.budget?.active_wake_id){
    active.append(node('span',`Active review: ${status.budget.active_wake_id} `));
    const button=node('button','View review');button.type='button';
    button.addEventListener('click',()=>showRun(status.budget.active_wake_id));active.append(button);
  }else active.textContent='No active review is recorded.';
}
function reviewButton(parent,wakeId,label='View source review'){
  if(!wakeId)return;
  const button=node('button',label,'review-link');button.type='button';
  button.addEventListener('click',()=>showRun(wakeId));parent.append(button);
}
function renderMemory(memory){
  const lessons=memory.lessons||[],reviews=memory.recent_reviews||[];
  $('memory-count').textContent=`${lessons.length} lessons · ${reviews.length} prior reviews${memory.truncated?' (bounded context)':''}`;
  const target=$('lessons');target.replaceChildren();
  for(const lesson of lessons){
    const card=node('article',undefined,'lesson');
    card.append(node('span',lesson.status==='owner_verified'?'Owner verified':'Model hypothesis',lesson.status==='owner_verified'?'pill':'pill hypothesis'));
    card.append(node('span',when(lesson.recorded_at),'muted'));
    paragraph(card,lesson.lesson);
    paragraph(card,`${lesson.source||'Source not recorded'}${lesson.owner?' · Owner: '+lesson.owner:''} · ${lesson.provenance||'Unknown provenance'}`,'muted');
    if(lesson.evidence?.length){const list=node('ul',undefined,'muted');for(const item of lesson.evidence)list.append(node('li',item));card.append(list);}
    if(lesson.corrects?.length)paragraph(card,'Corrects: '+lesson.corrects.join(', '),'muted');
    target.append(card);
  }
  if(!lessons.length)paragraph(target,'No explicit lessons have been saved yet. Prior model reviews remain hypotheses, not verified lessons.','empty');
  const prior=$('memory-reviews');prior.replaceChildren();
  for(const review of reviews){
    const card=node('article',undefined,'lesson');
    card.append(node('strong',`${when(review.generated_at)} · ${review.model||review.provider||'Review'}`));
    paragraph(card,review.summary);
    paragraph(card,'Model hypothesis · evidence from a prior review','muted');
    reviewButton(card,review.wake_id);prior.append(card);
  }
  if(!reviews.length)paragraph(prior,'No prior model review is available in saved context.','empty');
  const warnings=$('memory-limitations');warnings.replaceChildren();
  for(const warning of memory.limitations||[])paragraph(warnings,warning);
  if(memory.truncated)paragraph(warnings,`Context is bounded; ${memory.omitted?.reviews??'some'} reviews and ${memory.omitted?.lessons??'some'} lessons are omitted.`);
}
function renderRecommendations(recs){
  const open=(recs.recommendations||[]).filter(a=>!['resolved','declined'].includes(a.status));
  const advice=recs.model_recommendations||[];
  const actionCount=advice.reduce((count,item)=>count+(item.recommended_actions||[]).length,0);
  $('action-count').textContent=`${actionCount} model proposals · ${open.length} open handoffs`;
  const models=$('model-actions');models.replaceChildren();
  for(const item of advice.slice(0,10)){
    const card=node('article',undefined,'lesson');
    card.append(node('strong',`${when(item.created_at)} · ${item.model||item.provider||'Model review'}`));
    correctionNotices(card,item.corrections);
    paragraph(card,item.summary);
    strategy(card,item.strategic_assessment);
    for(const proposal of item.recommended_actions||[])action(card,proposal);
    paragraph(card,'Proposal only · execution is not established by this report','muted');
    reviewButton(card,item.wake_id);models.append(card);
  }
  if(advice.length>10||recs.model_truncated)paragraph(models,`Showing ${Math.min(advice.length,10)} reviews with advice from the recent ${recs.model_limit||100}-wake window. Open review history for other saved runs.`,'muted');
  if(!advice.length)paragraph(models,'No validated model advice is recorded in the recent review window.','empty');
  const handoffs=$('actions');handoffs.replaceChildren();
  for(const item of open){action(handoffs,item.body||{});paragraph(handoffs,`${item.status} · Notification: ${item.notification_status||'not sent'}`,'muted');}
  if(!open.length)paragraph(handoffs,'No incident handoffs await follow-up. Model advice appears above.','empty');
}

async function refresh(){const version=++loadVersion;$('refresh').disabled=true;try{const [status,history,costs,recs,memory]=await Promise.all(['/api/status','/api/runs','/api/costs','/api/recommendations','/api/memory'].map(p=>api(p)));if(version!==loadVersion)return;$('signin').hidden=true;$('dashboard').hidden=false;$('error').hidden=true;renderSchedule(status);renderMemory(memory);const b=costs.metaagent||status.budget||{};$('wake-cap').textContent=money(b.wake_limit_usd)+' maximum';$('day-cap').textContent=money(b.daily_limit_usd)+' maximum';$('day-cost').textContent=money(b.rolling_24h_actual_usd);$('remaining').textContent=money(b.rolling_24h_remaining_usd);$('pending').textContent=money(b.pending_reserved_usd);$('project-cost').textContent=money(costs.monitored_total_usd);$('coverage').textContent=costs.unknown_cost_agents?`${costs.truncated?'At least ':''}${costs.unknown_cost_agents} agents with unknown cost · ${money(costs.monitored_receipt_total_usd)} in receipts`:(costs.monitored_total_usd===null?'No monitored cost records':'Complete reported cost coverage');$('budget-meter').max=Number(b.daily_limit_usd||80);$('budget-meter').value=Number(b.rolling_24h_remaining_usd||0);$('updated').textContent='Updated '+when(status.generated_at);$('limits').textContent=`${money(b.wake_limit_usd)} per run · ${money(b.daily_limit_usd)} per rolling day`;
const runs=history.runs||[];$('run-count').textContent=`${runs.length} runs${history.truncated?' (newest shown)':''}`;$('runs').replaceChildren();$('empty-runs').hidden=runs.length>0;for(const run of runs){const tr=node('tr');for(const value of [when(run.started_at),run.model?`${run.provider||'Model'} / ${run.model}`:(run.provider||'See review'),run.outcome||run.status,money(run.actual_cost_usd),money(run.pending_reserved_usd)])tr.append(node('td',value));const td=node('td'),button=node('button','View');button.type='button';button.addEventListener('click',()=>showRun(run.wake_id));td.append(button);tr.append(td);$('runs').append(tr);}if(runs.length){$('latest-outcome').textContent=runs[0].outcome||runs[0].status;const latest=await api('/api/runs/'+encodeURIComponent(runs[0].wake_id));if(version!==loadVersion)return;review($('latest'),latest);}else{$('latest-outcome').textContent='No run yet';$('latest').replaceChildren(node('p','No review has run yet. Check the recorded schedule above; a free gate can exit without creating a model review.','muted'));}
renderRecommendations(recs);const agents=costs.agents||[];$('agent-count').textContent=`· ${agents.length} records${costs.truncated?' (partial inventory)':''}`;$('agents').replaceChildren();for(const a of agents){const tr=node('tr');for(const v of [a.name||a.agent_id,a.cost_status||'unknown',money(a.total_cost_usd),money(a.receipt_total_usd)])tr.append(node('td',v));$('agents').append(tr);}
}catch(e){$('error').textContent=e.message+' Existing values may be stale.';$('error').hidden=false;}finally{$('refresh').disabled=false;}}
$('refresh').addEventListener('click',refresh);$('close-dialog').addEventListener('click',()=>$('run-dialog').close());$('sso').href='https://hexapod.cwd1f0-new-cluster.coreweave.app/login?next='+encodeURIComponent(location.origin+'/');$('login').addEventListener('submit',async e=>{e.preventDefault();$('login-error').textContent='';try{await api('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:$('token').value})});$('token').value='';await refresh();}catch(error){$('login-error').textContent=error.message;}});refresh();
