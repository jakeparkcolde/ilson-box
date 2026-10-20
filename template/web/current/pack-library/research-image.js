"use strict";
// 일반 사진은 브라우저에서, HEIC는 인증된 실행기 메모리에서 변환한다. 분석에는 메타데이터를 제거한 JPEG 한 장만 사용한다.
const ResearchImage=(()=>{
 const get=id=>document.getElementById(id);
 let image=null,ready=false,busy=false,loading=false,blocked=false,heic=false,headers={},revision=0;
 function sync(){get("imagePicker").disabled=!ready||busy;get("removeImage").disabled=busy;get("question").required=!image;}
 function clear(){revision++;image=null;loading=false;blocked=false;get("imageFile").value="";get("imagePreview").hidden=true;get("attachedImage").hidden=false;get("removeImage").textContent="이미지 삭제";get("attachedImage").removeAttribute("src");get("imageStatus").textContent="";sync();}
 async function choose(files){
  if(busy)return;
  if(!ready){get("imageStatus").textContent="이미지 분석 연결이 없습니다. 실행기를 업데이트한 뒤 다시 열어주세요.";return;}
  clear();const ticket=revision;loading=true;blocked=true;
  try{
   if(files.length!==1)throw Error("이미지는 한 번에 한 장씩 첨부하세요.");
   const file=files[0];
   const isHeic=["image/heic","image/heif"].includes(file.type)||/\.hei[cf]$/i.test(file.name||"");
   if(!isHeic&&!["image/jpeg","image/png","image/webp"].includes(file.type))throw Error("JPG·PNG·WebP·HEIC 사진을 선택하세요.");
   if(!file.size||file.size>10*1024*1024)throw Error("10MB 이하의 이미지를 선택하세요.");
   get("imageStatus").textContent="이미지를 준비하고 있습니다…";
   let encoded;
   if(isHeic){
    if(!heic)throw Error("이 실행기는 HEIC 변환을 지원하지 않습니다. JPEG로 변환하거나 실행기를 업데이트하세요.");
    get("imageStatus").textContent="HEIC 사진을 변환하고 있습니다…";
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(Error("사진을 읽지 못했습니다."));reader.readAsDataURL(file);});
    if(ticket!==revision)return;
    const response=await fetch("/api/research/image",{method:"POST",headers:{"Content-Type":"application/json",...headers},body:JSON.stringify({media_type:"image/heic",data}),signal:AbortSignal.timeout(30000)});
    const result=await response.json();if(!response.ok)throw Error(result.error||"사진 변환에 실패했습니다.");
    if(result.image?.media_type!=="image/jpeg"||typeof result.image.data!=="string")throw Error("사진 변환 응답을 확인하지 못했습니다.");
    encoded=result.image.data;
   }else{
   const bitmap=await createImageBitmap(file);
   try{
    if(bitmap.width*bitmap.height>40000000)throw Error("이미지 해상도가 너무 큽니다. 사진을 줄여서 첨부하세요.");
    const canvas=document.createElement("canvas");
    for(const edge of [1600,1280,1024,800]){
     const scale=Math.min(1,edge/Math.max(bitmap.width,bitmap.height));canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
     const context=canvas.getContext("2d");context.fillStyle="#fff";context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(bitmap,0,0,canvas.width,canvas.height);
     for(const quality of [.88,.72,.55]){encoded=canvas.toDataURL("image/jpeg",quality).split(",")[1];if(encoded&&encoded.length<=320000)break;}
     if(encoded&&encoded.length<=320000)break;
    }
   }finally{bitmap.close();}
   }
   if(!encoded||encoded.length>320000)throw Error("이미지를 충분히 줄이지 못했습니다. 필요한 부분을 잘라 첨부하세요.");
   if(ticket!==revision)return;
   blocked=false;image={media_type:"image/jpeg",data:encoded};get("attachedImage").src="data:image/jpeg;base64,"+encoded;get("imagePreview").hidden=false;
   get("imageStatus").textContent="이미지 1장 준비됨 · 이어서 묻는 질문에도 사용합니다. 새 조사·삭제 시 해제되며 기록에는 저장하지 않습니다.";
  }catch(error){if(ticket===revision){blocked=true;get("imageStatus").textContent=(error.message||"이미지를 읽지 못했습니다.")+" 사진을 다시 첨부하거나 첨부 취소를 눌러주세요.";get("imagePreview").hidden=false;get("attachedImage").hidden=true;get("removeImage").textContent="첨부 취소";}}
  finally{if(ticket===revision){loading=false;sync();}}
 }
 function init(){
  get("imagePicker").addEventListener("click",()=>get("imageFile").click());
  get("imageFile").addEventListener("change",event=>choose([...event.target.files]));
  get("removeImage").addEventListener("click",clear);
  get("researchForm").addEventListener("paste",event=>{const files=[...event.clipboardData.files];if(files.length){event.preventDefault();choose(files);}});
  get("researchForm").addEventListener("dragover",event=>{if(event.dataTransfer.types.includes("Files"))event.preventDefault();});
  get("researchForm").addEventListener("drop",event=>{if(event.dataTransfer.files.length){event.preventDefault();choose([...event.dataTransfer.files]);}});
  sync();
 }
 return {init,clear,setReady(value,settings={}){ready=value;heic=settings.heic===true;headers=settings.headers||{};get("imagePicker").title=value?"JPG·PNG·WebP·HEIC, 최대 10MB · 붙여넣기 가능":"이미지 분석을 지원하는 실행기와 Pillow가 필요합니다";sync();},setBusy(value){busy=value;sync();},get(){return image;},isLoading(){return loading;},isBlocked(){return blocked;}};
})();
ResearchImage.init();
