'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name=studio-token]').content;
const fishLoginLink = document.createElement('a');
fishLoginLink.textContent = 'Fish 로그인 화면 열기 ↗';
fishLoginLink.target = '_blank';
fishLoginLink.rel = 'noopener noreferrer';
fishLoginLink.hidden = true;
$('fishState').after(fishLoginLink);
let job = null, selectedPhoto = 0, previewUrl = null, previewSequence = 0, previewTimer, dirtyScript = false;
let collection = null, collectionSelected = new Set(), sourceBusy = false, polling = false;
const exportCache = new Map();
const busyStates = new Set(['analyzing','recommending','quoting','generating','rendering','previewing']);
const numericControls = ['fontSize','posY','posX'];
const motionPromptCache = new Map();
let candidateSelected = new Set(), dirtyStyle = false;
const defaultMotionPrompt = 'Slow, subtle camera movement. Preserve the original architecture, furniture, colors, and lighting. Do not add or remove objects or people.';
async function api(path, body, binary=false) {
  const options = body === undefined ? {} : {method:'POST',headers:{'X-Studio-Token':token},body:body instanceof FormData ? body : JSON.stringify(body)};
  if(body !== undefined && !(body instanceof FormData)) options.headers['Content-Type']='application/json';
  const response = await fetch(path, options);
  if(!response.ok){let message;try{message=(await response.json()).detail;}catch{message=await response.text();}throw new Error(typeof message==='string'?message:JSON.stringify(message));}
  if(binary)return response.blob();
  const value=await response.json();
  if(path==='/api/connections'){
    fishLoginLink.hidden = true;
    if(value.fish_login_url){
      const url = new URL(value.fish_login_url);
      if(url.protocol === 'https:' && (url.hostname === 'fish.audio' || url.hostname.endsWith('.fish.audio'))){
        fishLoginLink.href = url.href;
        fishLoginLink.hidden = false;
      }
    }
    for(const button of document.querySelectorAll('[data-connect]')) {
      button.disabled = Boolean(value[button.dataset.connect + '_busy']);
    }
    const link=$('codexAuthUrl');
    const match=(value.codex_login||'').match(/https:\/\/auth\.openai\.com\/[^\s\x1b]+/);
    link.hidden=value.codex||!match;
    if(match)link.href=match[0];
  }
  return value;
}
function showError(error){$('status').className='error';$('statusTitle').textContent='확인이 필요해요.';$('statusDetail').textContent=error.message||String(error);}
function action(fn){return async()=>{try{await fn();}catch(error){showError(error);}};}
function numericValid(){return numericControls.every(id=>$(id+'Input').validity.valid);}
function caption(){if(!numericValid())throw new Error('글자 크기와 X/Y 위치의 입력 범위를 확인해 주세요.');return {font_size:Number($('fontSize').value),x:Number($('posX').value),y:Number($('posY').value),color:$('color').value,outline:Number($('outline').value),background_opacity:Number($('bgOpacity').value)/100,shadow:Number($('shadow').value)};}
function options(){return {max_motion:Number($('motion').value),caption:caption(),speed:Number($('speed').value)};}
function loadStyle(){if(!job)return;const c=job.options.caption;for(const [id,key] of [['fontSize','font_size'],['posX','x'],['posY','y'],['color','color'],['outline','outline'],['shadow','shadow']])$(id).value=c[key];for(const id of numericControls){$(id+'Input').value=$(id).value;$(id+'Error').hidden=true;$(id+'Input').removeAttribute('aria-invalid');}$('bgOpacity').value=Math.round(c.background_opacity*100);$('speed').value=String(job.options.speed);motionOptions();updateOutputs();}
function motionOptions(){
  $('motion').value=String(Math.min(job?.options.max_motion||0,job?.photos.length||0));
}
function updateOutputs(){$('bgOpacityValue').value=$('bgOpacity').value+'%';}
function queuePreview(){updateOutputs();clearTimeout(previewTimer);previewTimer=setTimeout(()=>updatePreview().catch(showError),180);}
async function updatePreview(){if(!job||!job.photos.length||!numericValid())return;if(job.preview||job.result){showVideo();return;}const sequence=++previewSequence;const blob=await api(`/api/jobs/${job.id}/preview`,{photo:selectedPhoto,text:$('captionText').value,caption:caption()},true);if(sequence!==previewSequence)return;if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=URL.createObjectURL(blob);$('preview').src=previewUrl;$('preview').hidden=false;$('previewEmpty').hidden=true;$('video').hidden=true;}
function drawPhotos(){
  const grid=$('photoGrid');grid.replaceChildren();$('photoCount').textContent=`사용 사진 ${job?job.photos.length:0}장`;if(!job)return;
  const order=job.photo_order?.length?job.photo_order:job.photos.map((_,i)=>i);
  order.forEach((index,position)=>{const photo=job.photos[index],card=document.createElement('div');card.className='ordered-photo';card.draggable=!planLocked();
    card.ondragstart=e=>e.dataTransfer.setData('text/plain',String(position));card.ondragover=e=>e.preventDefault();card.ondrop=e=>{e.preventDefault();const from=Number(e.dataTransfer.getData('text/plain'));if(Number.isInteger(from)&&from>=0&&from<order.length)movePhoto(from,position).catch(showError);};
    const button=document.createElement('button');button.title=photo.name;button.setAttribute('aria-label',`${position+1}번 사진 선택`);button.classList.toggle('selected',index===selectedPhoto);
    const image=document.createElement('img');image.src=`/api/jobs/${job.id}/files/${photo.file}`;image.alt=photo.name;image.loading='lazy';const number=document.createElement('span');number.textContent=String(position+1).padStart(2,'0');button.append(image,number);
    button.onclick=action(async()=>{selectedPhoto=index;drawPhotos();const scene=job.storyboard?.scenes.find(s=>s.photos.includes(index));if(scene)$('captionText').value=scene.caption_text??scene.text;await updatePreview();});
    const controls=document.createElement('div');controls.className='photo-moves';for(const [label,delta] of [['←',-1],['→',1]]){const move=document.createElement('button');move.textContent=label;move.setAttribute('aria-label',`${position+1}번 사진 ${delta<0?'앞':'뒤'}으로 이동`);move.disabled=planLocked()||position+delta<0||position+delta>=order.length;move.onclick=action(()=>movePhoto(position,position+delta));controls.append(move);}card.append(button,controls);
    const reason=job.storyboard?.selection_reasons?.[String(index)];if(reason){const details=document.createElement('small');details.textContent=reason;card.append(details);}grid.append(card);
  });drawCandidates();loadCrop();
}
function planLocked(){return Boolean(job&&(busyStates.has(job.state)||sourceBusy||job.pending_media||Object.values(job.generated).concat(Object.values(job.narration)).some(g=>['submitting','submitted'].includes(g.state)&&!g.file)||(job.workflow_version<2&&(Object.keys(job.narration).length||Object.values(job.generated).some(g=>g.generation_id||g.idempotency_key)))));}
function planValid(){return Boolean(job?.storyboard&&job.storyboard.scenes.every(s=>s.text.trim().length>0)&&job.storyboard.motion.every(m=>m.prompt.trim().length>0&&m.prompt.trim().length<=2000));}
function planChanged(){dirtyScript=true;drawStatus();}
function drawScript(){
  const panel=$('storyboard');panel.replaceChildren();
  if(!job?.storyboard){const p=document.createElement('p');p.className='muted';p.textContent='사진을 분석하면 장면별 대본이 여기에 나타납니다.';panel.append(p);drawMotion();return;}
  job.storyboard.scenes.forEach((scene,index)=>{
    const row=document.createElement('div');row.className='scene';
    const number=document.createElement('span');number.className='scene-number';number.textContent=String(index+1).padStart(2,'0');
    const body=document.createElement('div');body.className='scene-body';
    const text=document.createElement('textarea');text.value=scene.text;text.maxLength=160;text.disabled=planLocked();text.setAttribute('aria-label',`${index+1}번 장면 대본`);
    text.oninput=()=>{scene.text=text.value;planChanged();if(scene.photos.includes(selectedPhoto)&&scene.caption_text==null){$('captionText').value=text.value;queuePreview();}};
    const info=document.createElement('small');info.textContent='사진 '+scene.photos.map(n=>n+1).join(', ')+(job.storyboard.motion.some(m=>scene.photos.includes(m.photo))?' · 움직임 포함':'');
    const captionLabel=document.createElement('label');captionLabel.textContent='화면 자막 · 음성과 별도';const sub=document.createElement('textarea');sub.value=scene.caption_text??scene.text;sub.maxLength=320;sub.disabled=planLocked();sub.setAttribute('aria-label',`${index+1}번 장면 화면 자막`);sub.oninput=()=>{scene.caption_text=sub.value;planChanged();};captionLabel.append(sub);
    body.append(text,captionLabel,info,mediaControls('voice',index));row.append(number,body);panel.append(row);
  });drawMotion();
}
function drawMotion(){
  const grid=$('motionGrid'),prompts=$('motionPrompts');grid.replaceChildren();prompts.replaceChildren();
  $('savePlan').hidden=!job?.storyboard;
  if(!job?.storyboard){$('motionCount').textContent='0장 선택';return;}
  const selected=new Map(job.storyboard.motion.map(m=>[m.photo,m]));
  job.photos.forEach((photo,index)=>{
    const label=document.createElement('label');label.className='motion-photo';
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=selected.has(index);checkbox.dataset.photo=index;checkbox.setAttribute('aria-label',`${index+1}번 사진 움직임 선택`);
    checkbox.onchange=()=>{
      if(planLocked()){checkbox.checked=selected.has(index);return;}
      if(checkbox.checked){job.storyboard.motion.push({photo:index,prompt:motionPromptCache.get(index)||job.storyboard.motion_recommendations?.find(r=>r.photo===index)?.prompt||defaultMotionPrompt});}
      else{const previous=job.storyboard.motion.find(m=>m.photo===index);motionPromptCache.set(index,previous.prompt);job.storyboard.motion=job.storyboard.motion.filter(m=>m.photo!==index);}
      job.storyboard.motion.sort((a,b)=>a.photo-b.photo);dirtyScript=true;drawScript();drawStatus();
    };
    const img=document.createElement('img');img.src=`/api/jobs/${job.id}/files/${photo.file}`;img.alt=photo.name;img.loading='lazy';
    const text=document.createElement('span');text.textContent=`사진 ${index+1}`;const rec=job.storyboard.motion_recommendations?.find(r=>r.photo===index);if(rec){const why=document.createElement('small');why.textContent=(rec.recommended?'AI 추천 · ':'정지 권장 · ')+rec.reason;label.append(why);}label.append(img,checkbox,text);grid.append(label);
  });
  for(const motion of job.storyboard.motion){
    const label=document.createElement('label');label.className='motion-prompt';label.textContent=`사진 ${motion.photo+1} · 움직임 프롬프트`;
    const input=document.createElement('textarea');input.value=motion.prompt;input.maxLength=2000;input.dataset.photo=motion.photo;input.setAttribute('aria-label',`${motion.photo+1}번 사진 움직임 프롬프트`);
    const info=document.createElement('small');
    const update=()=>{const valid=motion.prompt.trim().length>0&&motion.prompt.trim().length<=2000;input.setAttribute('aria-invalid',String(!valid));info.textContent=valid?`${motion.prompt.trim().length} / 2,000자 · 한국어·영어 입력 가능`:'움직임을 설명하는 프롬프트를 1~2,000자로 입력하세요.';info.className=valid?'muted':'input-error';};
    input.oninput=()=>{motion.prompt=input.value;motionPromptCache.set(motion.photo,input.value);update();planChanged();};update();const rec=job.storyboard.motion_recommendations?.find(r=>r.photo===motion.photo);if(rec?.explanation){const why=document.createElement('p');why.className='muted';why.textContent=rec.explanation;label.append(why);}label.append(input,info,mediaControls('motion',motion.photo));prompts.append(label);
  }
  motionControls();
}
function motionControls(){
  const locked=planLocked(),count=job?.storyboard?.motion.length||0;
  $('motionCount').textContent=`${count}장 선택`;
  $('motionHelp').textContent=!job?.storyboard?'사진 분석 후 움직일 사진을 직접 고르고 프롬프트를 입력할 수 있어요.':locked?'제출한 생성 작업이 끝난 뒤 수정할 수 있어요.':count?'선택한 사진만 움직입니다. 사진마다 원하는 움직임을 입력하세요.':'선택한 움직임 사진이 없어요. 모든 사진을 정지 사진으로 사용합니다.';
  for(const checkbox of $('motionGrid').querySelectorAll('input'))checkbox.disabled=locked;
  for(const input of document.querySelectorAll('#motionPrompts textarea, #storyboard textarea'))input.disabled=locked;
  $('savePlan').disabled=locked||!planValid()||!numericValid();
  $('planNotice').textContent=dirtyScript?'변경 사항을 저장하거나 견적을 다시 확인해 주세요. 기존 견적은 사용할 수 없어요.':'';
}
async function savePlan(){
  if(!planValid()||planLocked())throw new Error('생성 전 대본과 움직임 프롬프트를 확인해 주세요.');
  caption();await planTransaction(persistPlan);
}
async function persistPlan(){job=await api(`/api/jobs/${job.id}/storyboard`,job.storyboard);dirtyScript=false;drawScript();}
async function planTransaction(fn){
  if(sourceBusy)throw new Error('현재 작업이 끝난 뒤 다시 진행해 주세요.');
  sourceBusy=true;drawStatus();
  try{await fn();}finally{sourceBusy=false;drawStatus();}
}
$('savePlan').onclick=action(savePlan);
function photosLocked(){return Boolean(job&&(busyStates.has(job.state)||job.pending_media||(job.workflow_version<2&&(job.storyboard||Object.keys(job.generated).length||Object.keys(job.narration).length||job.result))));}
function drawStatus(){
  const busy=sourceBusy||(job&&busyStates.has(job.state));
  const generated=job&&job.workflow_version<2&&(Object.keys(job.generated).length||Object.keys(job.narration).length||job.result);
  $('analyze').disabled=!job||busy||Boolean(generated)||!numericValid(); $('saveStyle').disabled=!job||busy||!numericValid(); $('quote').disabled=!job?.storyboard||busy||!numericValid()||!planValid();
  $('newJob').disabled=sourceBusy; $('files').disabled=sourceBusy||photosLocked();
  $('dropZone').classList.toggle('locked',$('files').disabled); $('photoLockNote').hidden=!photosLocked();
  $('sourceNames').hidden=!job?.sources?.length;
  $('sourceNames').textContent=(job?.sources||[]).map(s=>s.name).join(' / ');
  $('status').className=job?.state==='error'?'error':busy?'busy':'';
  $('statusTitle').textContent=sourceBusy?'작업을 준비하고 있어요.':job?.message||'사진을 기다리고 있어요.';
  $('statusDetail').textContent=job?.error||'사진 구성 → 대본 → 크레딧 승인 → 1080p 영상 미리보기 → 내보내기';drawPreviewStatus(busy);
  $('quoteBox').hidden=job?.state!=='awaiting_approval'||!job?.quote||dirtyScript;
  $('approve').disabled=busy||dirtyScript||!numericValid();
  if(job?.quote){$('credits').textContent=job.quote.total.toLocaleString()+' credits';$('quoteBreakdown').textContent=`움직임 ${job.quote.videos.length}장 · Drama3 음성 ${job.quote.voices.length}장면`;}
  const audioReady=job?.storyboard&&job.storyboard.scenes.every((s,i)=>job.narration[String(i)]?.file);
  $('rerender').hidden=!audioReady||busy||job.workflow_version>=2; $('resume').hidden=!job?.approval||busy||['complete','preview_ready'].includes(job.state);
  $('rerender').disabled=!numericValid();$('resume').disabled=dirtyScript||!numericValid();
  $('exportNotice').textContent=busy?'작업이 진행 중이에요. 파일이 준비되면 다운로드할 수 있어요.':job?.result?'준비된 파일을 각각 다운로드하세요.':'영상 생성이 끝나면 아래 파일을 각각 다운로드할 수 있어요.';
  if(job?.available_exports)exportCache.set(job.id,job.available_exports);
  const available=new Set(job?(exportCache.get(job.id)||[]):[]);
  for(const [id,name] of [['download','stay-reel.mp4'],['videoDownload','stay-video.mp4'],['scriptDownload','stay-script.txt'],['subtitleDownload','stay-reel.srt'],['audioDownload','stay-voice.mp3']]){
    const ready=Boolean(job?.result&&available.has(name)&&!busy);
    $(id).hidden=!ready; $(id).removeAttribute('href');
    if(ready){$(id).href=`/api/jobs/${job.id}/files/${name}`;$(id).download=name;}
    if($(id+'Missing')){
      $(id+'Missing').hidden=ready;
      $(id+'Missing').textContent=busy?'생성 중':!job?.result?'생성 후 다운로드':id==='scriptDownload'?'TXT는 다시 합성해 주세요':'다시 합성해 주세요';
    }
  }
  for(const button of document.querySelectorAll('.history-job'))button.disabled=sourceBusy;
  drawCollection();
  motionControls();
  for(const id of [...numericControls,...numericControls.map(id=>id+'Input'),'captionText','color','outline','bgOpacity','shadow','speed','motion'])$(id).disabled=Boolean(busy);
  $('motion').disabled=Boolean(busy)||!job;
}
async function selectJob(id){job=await api('/api/jobs/'+id);dirtyScript=dirtyStyle=false;candidateSelected.clear();motionPromptCache.clear();selectedPhoto=job.photo_order?.[0]??job.storyboard?.scenes[0]?.photos[0]??0;loadStyle();drawPhotos();drawScript();drawStatus();const scene=job.storyboard?.scenes.find(s=>s.photos.includes(selectedPhoto));if(scene)$('captionText').value=scene.caption_text??scene.text;await updatePreview();showVideo();}
async function upload(files){
  if(!files.length)return;
  if(sourceBusy||photosLocked())throw new Error('현재 생성 작업이 끝난 뒤 사진을 추가해 주세요.');
  const target=job?.id,form=new FormData();for(const file of files)form.append('files',file);
  sourceBusy=true;drawStatus();
  try{job=await api(target?`/api/jobs/${target}/${job.workflow_version>=2?'candidates':'photos'}`:'/api/jobs',form);selectedPhoto=job.photo_order?.[0]??0;loadStyle();drawPhotos();drawScript();await updatePreview();await history();}
  finally{sourceBusy=false;$('files').value='';drawStatus();}
}
async function history(){const list=await api('/api/jobs');$('history').replaceChildren();for(const item of list.slice(0,10)){const button=document.createElement('button');button.className='history-job';button.textContent=`${item.name?item.name+' · ':''}사진 ${item.photos}장 · ${item.message}`;button.disabled=sourceBusy;button.onclick=action(()=>selectJob(item.id));$('history').append(button);}}
async function connections(){const value=await api('/api/connections');$('codexState').textContent=value.codex?'ChatGPT 구독 연결됨':'로그인이 필요합니다';$('fishState').textContent=value.fish?'Fish MCP 연결됨':'패키지 크레딧 계정 연결 필요';$('loginMessage').textContent=value.codex_login;$('connectMessage').textContent=value.message;if(value.workspaces.length){const old=$('workspace').value;$('workspace').replaceChildren();for(const item of value.workspaces){const option=document.createElement('option');option.value=item.workspace_id;option.textContent=item.workspace_name;$('workspace').append(option);}if([...$('workspace').options].some(o=>o.value===old))$('workspace').value=old;}return value;}
function collectionControls(){
  const collecting=collection?.status==='in_progress',locked=sourceBusy||photosLocked();
  $('collectPhotos').disabled=locked||collecting; $('stayUrl').disabled=sourceBusy||collecting;
  const remaining=job?.workflow_version>=2?60:60-(job?.photos.length||0),selected=collectionSelected.size;
  $('collectionCount').textContent=`${selected}장 선택 · ${remaining}장까지 추가`;
  $('selectCollection').textContent=`최대 ${remaining}장 선택`;
  $('selectCollection').disabled=locked||collecting||remaining<=0;
  $('clearCollection').disabled=sourceBusy||collecting;
  $('importPhotos').disabled=locked||collecting||!selected||selected>remaining;
  $('importPhotos').textContent=selected?`선택한 ${selected}장 추가`:'선택한 사진 추가';
}
function drawCollection(){
  $('collectionGallery').hidden=!collection?.photos.length;
  collectionControls();
  if(!collection)return;
  $('collectionName').textContent=collection.name||'수집한 숙소 사진';
  $('collectionStatus').textContent=collection.error?`${collection.message} ${collection.error}`:
    `${collection.message}${collection.status==='in_progress'?' · 수집이 끝나면 사진을 선택할 수 있어요.':''}`;
  const grid=$('collectionGrid');grid.replaceChildren();
  const existing=new Set((job?.photos||[]).map(p=>p.sha256));
  for(const photo of collection.photos){
    const already=existing.has(photo.id),disabled=!photo.usable||already||sourceBusy||photosLocked()||collection.status==='in_progress';
    if(already||!photo.usable)collectionSelected.delete(photo.id);
    const label=document.createElement('label');label.className='collection-photo';label.classList.toggle('unusable',!photo.usable||already);
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.value=photo.id;checkbox.checked=collectionSelected.has(photo.id);checkbox.disabled=disabled;
    const title=[...new Set(photo.labels.map(l=>l.title||l.room_name).filter(Boolean))].join(' · ')||'숙소 사진';
    checkbox.setAttribute('aria-label',`${title} 사진 선택`);
    checkbox.onchange=()=>{if(checkbox.checked)collectionSelected.add(photo.id);else collectionSelected.delete(photo.id);collectionControls();};
    const image=document.createElement('img');image.src=`/api/collections/${collection.id}/photos/${photo.id}`;image.alt=title;image.loading='lazy';
    const text=document.createElement('span');text.textContent=`${title} · ${photo.width}×${photo.height}${already?' · 이미 추가됨':!photo.usable?' · 사용 불가':''}`;
    if(!photo.usable)label.title=photo.reason;
    label.append(image,checkbox,text);grid.append(label);
  }
  $('collectionFailures').hidden=!collection.failures.length;
  $('collectionFailureList').replaceChildren();
  for(const failure of collection.failures){const item=document.createElement('li');item.textContent=`${failure.labels?.map(l=>l.title||l.room_name).filter(Boolean).join(' · ')||'사진'}: ${failure.error}`;$('collectionFailureList').append(item);}
  collectionControls();
}
$('collectPhotos').onclick=action(async()=>{
  const url=$('stayUrl').value.trim();if(!url)throw new Error('여기어때 국내 숙소 상세 링크를 입력해 주세요.');
  sourceBusy=true;drawStatus();$('collectionStatus').textContent='수집을 시작하고 있어요.';
  try{collection=await api('/api/collections',{url});collectionSelected.clear();try{localStorage.setItem('stayCollection',collection.id);}catch{};}
  finally{sourceBusy=false;drawStatus();}
});
$('stayUrl').addEventListener('keydown',event=>{if(event.key==='Enter'&&!$('collectPhotos').disabled){event.preventDefault();$('collectPhotos').click();}});
$('selectCollection').onclick=()=>{
  const existing=new Set((job?.photos||[]).map(p=>p.sha256));
  collectionSelected=new Set(collection.photos.filter(p=>p.usable&&!existing.has(p.id)).slice(0,60-(job?.photos.length||0)).map(p=>p.id));drawCollection();
};
$('clearCollection').onclick=()=>{collectionSelected.clear();drawCollection();};
$('importPhotos').onclick=action(async()=>{
  sourceBusy=true;drawStatus();
  try{job=await api('/api/composition',{collection_id:collection.id,photos:[...collectionSelected],job_id:job?.id,mode:'manual'});collectionSelected.clear();selectedPhoto=0;loadStyle();drawPhotos();drawScript();await updatePreview();await history();}
  finally{sourceBusy=false;drawStatus();}
});
async function restoreCollection(){
  let id;try{id=localStorage.getItem('stayCollection');}catch{return;}
  if(!id)return;
  try{collection=await api('/api/collections/'+id);$('stayUrl').value=collection.source_url;drawCollection();}
  catch{try{localStorage.removeItem('stayCollection');}catch{}}
}
$('files').onchange=action(()=>upload([...$('files').files]));for(const event of ['dragenter','dragover'])$('dropZone').addEventListener(event,e=>{e.preventDefault();if(!$('files').disabled)$('dropZone').classList.add('dragover');});$('dropZone').addEventListener('dragleave',()=>$('dropZone').classList.remove('dragover'));$('dropZone').addEventListener('drop',e=>{e.preventDefault();$('dropZone').classList.remove('dragover');upload([...e.dataTransfer.files]).catch(showError);});
for(const id of ['color','outline','bgOpacity','shadow','captionText'])$(id).addEventListener('input',queuePreview);
for(const id of numericControls){
  $(id).addEventListener('input',()=>{$(id+'Input').value=$(id).value;$(id+'Error').hidden=true;$(id+'Input').removeAttribute('aria-invalid');queuePreview();drawStatus();});
  $(id+'Input').addEventListener('input',()=>{const valid=$(id+'Input').validity.valid;$(id+'Error').hidden=valid;$(id+'Input').setAttribute('aria-invalid',String(!valid));if(valid){$(id).value=$(id+'Input').value;queuePreview();}else{++previewSequence;clearTimeout(previewTimer);}drawStatus();});
}
$('newJob').onclick=()=>{job=null;dirtyScript=dirtyStyle=false;candidateSelected.clear();motionPromptCache.clear();motionOptions();++previewSequence;$('files').value='';drawPhotos();drawScript();drawStatus();$('preview').hidden=$('video').hidden=true;$('previewEmpty').hidden=false;};
$('analyze').onclick=action(async()=>{await api(`/api/jobs/${job.id}/analyze`,options());job=await api('/api/jobs/'+job.id);drawStatus();});
$('saveStyle').onclick=action(async()=>{const settings=options(),draft=job.storyboard;await planTransaction(async()=>{job=await api(`/api/jobs/${job.id}/style`,settings);if(dirtyScript)job.storyboard=draft;});$('statusTitle').textContent='자막 설정을 저장했어요. 다시 합성하면 완성 영상에 적용됩니다.';});
$('quote').onclick=action(async()=>{const settings=options(),workspace=$('workspace').value;if(!planValid())throw new Error('움직임 프롬프트와 대본을 확인해 주세요.');await planTransaction(async()=>{if(dirtyScript)await persistPlan();await api(`/api/jobs/${job.id}/style`,settings);await api(`/api/jobs/${job.id}/quote`,{workspace});job=await api('/api/jobs/'+job.id);drawScript();});});
$('approve').onclick=action(async()=>{if(dirtyScript||!job.quote)throw new Error('대본·움직임이 바뀌었습니다. 견적을 다시 확인해 주세요.');const settings=options(),approval={quote_id:job.quote.id,expected_credits:job.quote.total};await planTransaction(async()=>{await api(`/api/jobs/${job.id}/style`,settings);await api(`/api/jobs/${job.id}/approve`,approval);job=await api('/api/jobs/'+job.id);drawScript();});});
$('rerender').onclick=action(async()=>{await api(`/api/jobs/${job.id}/style`,options());await api(`/api/jobs/${job.id}/render`,{});job=await api('/api/jobs/'+job.id);drawStatus();});
$('resume').onclick=action(async()=>{await api(`/api/jobs/${job.id}/resume`,{});job=await api('/api/jobs/'+job.id);drawStatus();});
$('settingsButton').onclick=()=>{$('settings').showModal();connections().catch(showError);};$('closeSettings').onclick=()=>$('settings').close();for(const button of document.querySelectorAll('[data-connect]'))button.onclick=action(async()=>{await api('/api/connect/'+button.dataset.connect,{});await connections();});
$('recoverVoice').onclick=action(async()=>{if(!job)throw new Error('작업을 먼저 선택해 주세요.');const file=$('recoverFile').files[0];if(!file)throw new Error('음성 파일을 선택해 주세요.');const data=new FormData();data.append('file',file);await api(`/api/jobs/${job.id}/recover-voice/${Number($('recoverScene').value)-1}`,data);await selectJob(job.id);$('connectMessage').textContent='음성을 복구했습니다.';});
setInterval(async()=>{
  if(polling)return;polling=true;
  try{
    if(job&&busyStates.has(job.state)){
      const id=job.id,previous=job.state,next=await api('/api/jobs/'+id);
      if(job?.id===id){job=next;drawStatus();if(previous!==job.state){drawScript();drawPhotos();if(job.state==='uploaded'&&job.storyboard){loadStyle();$('captionText').value=job.storyboard.scenes[0].text;await updatePreview();}if(['complete','preview_ready'].includes(job.state))await selectJob(job.id);await history();}}
    }
    if(collection?.status==='in_progress'){
      const id=collection.id,next=await api('/api/collections/'+id);if(collection?.id===id){collection=next;drawCollection();}
    }
    if($('settings').open)await connections();
  }catch(error){showError(error);}finally{polling=false;}
},2000);
function compositionMode(){return document.querySelector('input[name=compositionMode]:checked').value;}
let cropUrl=null,cropTimer,cropSequence=0;
function loadCrop(){const focus=job?.storyboard?.crop_focus.find(f=>f.photo===selectedPhoto);$('cropX').value=focus?.x??0.5;$('cropY').value=focus?.y??0.5;for(const id of ['cropX','cropY'])$(id).disabled=!job?.storyboard||planLocked();$('cropPreview').hidden=true;}
async function updateCrop(){
  if(!job?.storyboard||planLocked())return;
  const sequence=++cropSequence,x=Number($('cropX').value),y=Number($('cropY').value);
  let focus=job.storyboard.crop_focus.find(f=>f.photo===selectedPhoto);if(!focus){focus={photo:selectedPhoto,x,y};job.storyboard.crop_focus.push(focus);}Object.assign(focus,{x,y});planChanged();
  const blob=await api(`/api/jobs/${job.id}/preview`,{photo:selectedPhoto,text:'',caption:caption(),focus:{x,y}},true);if(sequence!==cropSequence)return;if(cropUrl)URL.revokeObjectURL(cropUrl);cropUrl=URL.createObjectURL(blob);$('cropPreview').src=cropUrl;$('cropPreview').hidden=false;
}
async function mediaUrl(key){const bytes=new TextEncoder().encode(JSON.stringify(key));const hash=await crypto.subtle.digest('SHA-256',bytes);return `/api/jobs/${job.id}/media/${[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('')}`;}
function showVideo(){
  const asset=job?.preview||job?.result;if(!asset)return;
  const url=`/api/jobs/${job.id}/files/${asset.file}`;
  if($('video').getAttribute('src')!==url)$('video').src=url;
  $('preview').hidden=true;$('previewEmpty').hidden=true;$('video').hidden=false;
}
function drawPreviewStatus(busy){
  for(const id of ['cropX','cropY'])$(id).disabled=busy||!job?.storyboard||planLocked();
  const stale=Boolean(job?.preview&&(job.preview_stale||!['preview_ready','complete'].includes(job.state)));
  const latest=job?.preview&&!stale&&!dirtyScript&&!dirtyStyle;
  const mediaReady=job?.media_ready??(job?.storyboard&&job.storyboard.scenes.every((s,i)=>job.narration[String(i)]?.file)&&job.storyboard.motion.every(m=>job.generated[String(m.photo)]?.file));
  $('previewVideo').disabled=!mediaReady||busy||!numericValid();
  $('exportFinal').disabled=!latest||busy;
  $('previewNote').textContent=stale||dirtyScript||dirtyStyle?'변경 전 영상입니다. 미리보기를 업데이트한 뒤 내보내세요.':job?.preview?`1080×1920 · 30fps · ${job.preview.duration.toFixed(1)}초 · 실제 AI 움직임·음성·자막`:'첫 생성 후 AI 움직임·음성·자막이 포함된 1080p 영상으로 확인합니다.';
  $('paceWarning').textContent=(job?.preview?.warnings||[]).join(' ');
  $('recommend').disabled=busy||(!job&&!collection)||Boolean(job?.pending_media)||!$('targetCount').validity.valid;
  $('versionsPanel').hidden=!job?.versions?.length;$('versionsList').replaceChildren();
  for(const [i,v] of (job?.versions||[]).entries()){const button=document.createElement('button');button.className='quiet';button.textContent=`구성 ${i+1} · 사진 ${v.photos.length}장 복원`;button.disabled=busy;button.onclick=action(async()=>{job=await api(`/api/jobs/${job.id}/versions/${i}`,{});await selectJob(job.id);});$('versionsList').append(button);}
  showVideo();
}
function drawCandidates(){
  const pool=job?.candidates||[];$('candidatePanel').hidden=!pool.length;$('candidateCount').textContent=`후보 사진 ${pool.length}장 · 현재 영상 ${job?.photos.length||0}장`;
  $('candidateGrid').replaceChildren();
  for(const photo of pool){const label=document.createElement('label');label.className='collection-photo';const input=document.createElement('input');input.type='checkbox';input.checked=candidateSelected.has(photo.id);input.disabled=planLocked();input.onchange=()=>{if(input.checked)candidateSelected.add(photo.id);else candidateSelected.delete(photo.id);drawCandidates();};input.setAttribute('aria-label',`${photo.name||'후보'} 사진 선택`);const img=document.createElement('img');img.loading='lazy';img.alt=photo.name||'후보 사진';img.src=photo.collection_id?`/api/collections/${photo.collection_id}/photos/${photo.id}`:`/api/jobs/${job.id}/files/${photo.file}`;const text=document.createElement('span');text.textContent=candidateSelected.has(photo.id)?`선택 순서 ${[...candidateSelected].indexOf(photo.id)+1}`:photo.name||'후보 사진';label.append(img,input,text);$('candidateGrid').append(label);}
  $('applyCandidates').disabled=planLocked()||!candidateSelected.size||candidateSelected.size>60;
}
async function movePhoto(from,to){
  if(planLocked())return;
  if(dirtyScript)await persistPlan();
  const order=job.photo_order?.length?[...job.photo_order]:job.photos.map((_,i)=>i);
  const [photo]=order.splice(from,1);order.splice(to,0,photo);
  job=await api('/api/composition',{job_id:job.id,mode:'manual',order});await selectJob(job.id);
}
function mediaControls(kind,index){
  const box=document.createElement('div');box.className='media-controls';if(job?.workflow_version<2)return box;
  const retry=document.createElement('button');retry.type='button';retry.className='quiet';retry.textContent=kind==='voice'?'이 음성 다시 생성':'이 움직임 다시 생성';retry.disabled=planLocked();retry.onclick=action(async()=>{if(dirtyScript)await persistPlan();job=await api(`/api/jobs/${job.id}/media-attempt`,{kind,index});await selectJob(job.id);$('statusDetail').textContent='새 결과를 생성하려면 변경분 견적을 확인하고 크레딧 사용을 승인하세요.';});box.append(retry);
  const active=(kind==='voice'?job.narration:job.generated)[String(index)];
  const matching=active?.asset_key?active.asset_key.slice(0,active.asset_key.lastIndexOf(':')):Object.keys(job.assets||{}).find(k=>{const r=job.assets[k];return kind==='voice'?r.text===job.storyboard.scenes[index].text:r.photo_sha===job.photos[index].sha256&&r.prompt===job.storyboard.motion.find(m=>m.photo===index)?.prompt;})?.replace(/:\d+$/,'');
  if(matching){
    const select=document.createElement('select');select.setAttribute('aria-label','이전 생성 결과 선택');
    for(const [key,record] of Object.entries(job.assets)){if(key.startsWith(matching+':')&&record.file){const option=document.createElement('option');option.value=key.split(':').at(-1);option.textContent=`생성 결과 ${Number(option.value)+1}`;select.append(option);}}
    if(select.options.length){
      const restore=document.createElement('button');restore.type='button';restore.className='quiet';restore.textContent='결과 복원';restore.disabled=planLocked();restore.onclick=action(async()=>{if(dirtyScript)await persistPlan();job=await api(`/api/jobs/${job.id}/media-attempt`,{kind,index,restore:Number(select.value)});await selectJob(job.id);});
      const player=document.createElement(kind==='voice'?'audio':'video');player.controls=true;player.preload='none';player.className='asset-player';
      const update=()=>mediaUrl(matching+':'+select.value).then(url=>{player.src=url;}).catch(showError);select.onchange=update;update();box.append(select,restore,player);
    }
  }
  return box;
}
for(const radio of document.querySelectorAll('input[name=compositionMode]'))radio.onchange=()=>{$('aiControls').hidden=compositionMode()!=='ai';$('compositionHelp').textContent=compositionMode()==='ai'?'사진이 많아도 전체 후보를 비교해 숙소의 매력을 보여 주는 순서로 추천합니다.':'선택한 순서를 그대로 사용합니다. 사진을 끌거나 이동 버튼으로 순서를 바꾸세요.';drawStatus();};
$('targetCount').oninput=drawStatus;
for(const id of ['cropX','cropY'])$(id).oninput=()=>{clearTimeout(cropTimer);cropTimer=setTimeout(()=>updateCrop().catch(showError),150);};
for(const id of [...numericControls,...numericControls.map(id=>id+'Input'),'color','outline','bgOpacity','shadow','speed'])$(id).addEventListener('input',()=>{dirtyStyle=true;drawStatus();});
$('captionText').addEventListener('input',()=>{const scene=job?.storyboard?.scenes.find(s=>s.photos.includes(selectedPhoto));if(scene&&!planLocked()){scene.caption_text=$('captionText').value;planChanged();drawScript();}});
$('recommend').onclick=action(async()=>{if(!$('targetCount').validity.valid)throw new Error('추천 장수는 1~60장입니다.');if(dirtyScript)await persistPlan();job=await api('/api/composition',{job_id:job?.id,collection_id:collection?.id,mode:'ai',target_count:Number($('targetCount').value)});job=await api('/api/jobs/'+job.id);drawStatus();});
$('applyCandidates').onclick=action(async()=>{job=await api('/api/composition',{job_id:job.id,mode:'manual',photos:[...candidateSelected]});candidateSelected.clear();await selectJob(job.id);});
$('previewVideo').onclick=action(async()=>{await planTransaction(async()=>{if(dirtyScript)await persistPlan();await api(`/api/jobs/${job.id}/style`,options());await api(`/api/jobs/${job.id}/preview-video`,{});job=await api('/api/jobs/'+job.id);});});
$('exportFinal').onclick=action(async()=>{await api(`/api/jobs/${job.id}/render`,{});job=await api('/api/jobs/'+job.id);drawStatus();});
drawStatus();restoreCollection();history().catch(showError);connections().then(value=>{if(!value.codex||!value.fish)$('settings').showModal();}).catch(showError);
