(()=>{
const INIT=(tg&&tg.initData)||new URLSearchParams(location.hash.slice(1)).get("tgWebAppData")||"";
async function api(b){const r=await fetch("/api/act",{method:"POST",headers:{"Content-Type":"application/json","X-Init":INIT},body:JSON.stringify(b)});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||"Нет связи с сервером");return j}
// применить состояние сервера; true, если изменился гардероб
function ap(s){const n=S.inv.length+S.sold;(s.ev||[]).forEach(toast);Object.assign(S,s);S.daily=s.dc?today:"";tp();return n!=S.inv.length+S.sold}
const act=(b,m)=>api(b).then(r=>{ap(r);render();if(m)toast(m);return r}).catch(e=>{toast(e.message)});
settle=()=>false;
mkList=()=>act({a:"state"});
A.buy=id=>act({a:"buy",id},"Куплено!");
A.daily=()=>act({a:"daily"},"+10 000 ₽");
A.claim=(k,r)=>act({a:"claim",k},"+"+fm(r));
A.sellMany=ids=>act({a:"sell",ids});
A.reset2=()=>api({a:"reset"}).then(()=>location.reload()).catch(e=>toast(e.message));
A.open=async function(){
  if(P.busy)return;if(!pool().length)return toast("Нет таких предметов: смените категорию или ранг");
  P.busy=true;$(".box").classList.add("go");const t0=Date.now();
  try{const r=await api({a:"open",m:P.min,c:P.cat,n:P.n});
    await new Promise(z=>setTimeout(z,Math.max(0,1900-(Date.now()-t0))));
    ap(r);P.busy=false;P.last=r.res;render();sheet(r.res,r.cost)}
  catch(e){P.busy=false;render();toast(e.message)}};
A.bid=()=>api({a:"bid",id:AV,amt:+$("#bi").value}).then(r=>{ap(r);ash();toast("Ставка принята")}).catch(e=>toast(e.message));
A.auGo=u=>api({a:"auc",u,sp:+$("#sp").value,d:AD}).then(r=>{ap(r);closeOv();M.seg="a";AF="mine";tab="market";W.sel=null;render();toast("Лот выставлен")}).catch(e=>toast(e.message));
// рейтинг и рефералы
let LB=[];
const lbH=()=>`<h3>Рейтинг по коллекции</h3><div class="cd">${LB.length?LB.map((r,k)=>`<div class="row" style="padding:4px 0${r.me?";color:var(--gr);font-weight:700":""}"><span>${k+1}. ${r.n}</span><b>${fm(r.s)}</b></div>`).join(""):'<span class="mu">Загрузка…</span>'}</div>`;
const vm=V.more;V.more=()=>vm().replace(/<h3>Скоро[\s\S]*?<\/div>/,lbH());
const vf=V.friends;V.friends=()=>vf().replace("<b>0</b>",`<b>${S.refs||0}</b>`).replace(/Награды за друзей[^<]*/,"За каждого друга по вашей ссылке: +20 000 ₽.");
const go=A.go;A.go=t=>{go(t);if(t=="more")api({a:"top"}).then(r=>{LB=r.top;if(tab=="more")render()}).catch(()=>{})};
// синхронизация аукционов и рынка
setInterval(()=>{if(document.hidden||P.busy)return;api({a:"state"}).then(s=>{
  const ch=ap(s);
  if(tab=="market"&&$("#lst"))$("#lst").innerHTML=M.seg=="a"?alist():mlist();
  else if(ch&&(tab=="wardrobe"||tab=="more"))render();
  if(AV&&$("#ov").classList.contains("on")){const b=$("#bi"),v=b&&b.value;ash();if(v&&$("#bi"))$("#bi").value=v}
}).catch(()=>{})},4000);
api({a:"state"}).then(s=>{ap(s);render()}).catch(e=>toast(e.message));
})();
