const $ = s => document.querySelector(s);
const state = { data: [], example: "", out: "", lastReport: "" };

async function api(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body||{})});
  return r.json();
}
function setPath(el, text, empty){ el.textContent = text; el.classList.toggle("empty", !!empty); }

// ---- key status ----
function renderKey(k){
  const chip = $("#keyChip"), st = $("#keyState");
  if(k.has_key){
    chip.textContent = "Key: " + k.masked; chip.style.color = "var(--ok)";
    const src = k.source === "gui" ? "saved locally" : (k.source === "env" ? "from env var" : k.source);
    st.textContent = k.masked + " · " + src; st.className = "badge ok";
  } else {
    chip.textContent = "Key: not set"; chip.style.color = "var(--warn)";
    st.textContent = "not set"; st.className = "badge warn";
  }
  $("#cfgPath").textContent = k.config_path || "~/.statreport/config.json";
}
function fillSelect(sel, items, current){
  sel.innerHTML = "";
  items.forEach(m=>{ const o=document.createElement("option"); o.value=o.textContent=m; if(m===current)o.selected=true; sel.appendChild(o); });
}

// ---- init ----
fetch("/config").then(r=>r.json()).then(c=>{
  state.out = c.default_out; setPath($("#outPath"), c.default_out, false);
  fillSelect($("#model"), c.models, c.key.model);
  fillSelect($("#narrativeModel"), c.narrative_models, c.key.narrative_model);
  renderKey(c.key);
  const e = c.engines || {};
  const tag = (ok,label)=>`<span class="badge ${ok?'ok':'warn'}">${label}</span>`;
  $("#engineStatus").innerHTML = "Detected: " +
    tag(e.rscript,"Rscript") + " " + tag(e.quarto,"Quarto") + " " + tag(e.pandoc,"pandoc") +
    (e.rscript ? "" : " — Python engine will be used (always available).");
});

$("#keyChip").onclick = ()=>{ $("#settings").open = true; $("#settings").scrollIntoView({behavior:"smooth"}); };
$("#keySave").onclick = async ()=>{
  const key = $("#keyInput").value.trim();
  if(!key){ $("#keyMsg").textContent = "Enter a key first."; return; }
  const r = await api("/key", {key, model:$("#model").value, narrative_model:$("#narrativeModel").value});
  if(r.ok){ renderKey(r.key); $("#keyInput").value=""; $("#keyMsg").textContent="Saved locally."; }
  else $("#keyMsg").textContent = "Error: " + (r.error||"?");
};
$("#keyTest").onclick = async ()=>{
  $("#keyMsg").textContent = "Testing…";
  const r = await api("/key/test", {});
  $("#keyMsg").textContent = r.ok ? `Key works — ${r.model_count} models available (${r.source}).` : "Test failed: " + (r.error||"?");
};
$("#keyClear").onclick = async ()=>{ const r = await api("/key/clear", {}); renderKey(r.key); $("#keyMsg").textContent="Key cleared."; };

// ---- pickers ----
$("#pickData").onclick = async ()=>{ const r = await api("/pick",{kind:"files"}); if(r.expanded&&r.expanded.length){ state.data=r.expanded; showData(); } };
$("#pickDataFolder").onclick = async ()=>{ const r = await api("/pick",{kind:"folder"}); if(r.expanded&&r.expanded.length){ state.data=r.expanded; showData(); } };
$("#pickEx").onclick = async ()=>{ const r = await api("/pick",{kind:"file"}); if(r.paths&&r.paths[0]){ state.example=r.paths[0]; setPath($("#exPath"),state.example.split("/").pop(),false); } };
$("#exClear").onclick = ()=>{ state.example=""; setPath($("#exPath"),"none",true); };
$("#pickOut").onclick = async ()=>{ const r = await api("/pick",{kind:"folder"}); if(r.paths&&r.paths[0]){ state.out=r.paths[0]; setPath($("#outPath"),state.out,false); } };
$("#openOut").onclick = ()=> api("/openfolder",{dir:state.out});
$("#openReport").onclick = ()=> api("/openfolder",{dir:state.lastReport||state.out});
function showData(){
  const n=state.data.length, names=state.data.slice(0,3).map(p=>p.split("/").pop()).join(", ");
  setPath($("#dataPath"), n?`${n} file(s): ${names}${n>3?" +"+(n-3):""}`:"none selected", !n);
}

function radio(name){ return document.querySelector(`input[name=${name}]:checked`).value; }

// ---- run ----
$("#run").onclick = ()=>{
  if(!state.data.length){ alert("Choose a data file first."); return; }
  const wf = radio("wf");
  if((wf==="example"||wf==="combo") && !state.example){ alert("This workflow needs an example report."); return; }
  const cfg = {
    data: state.data, example: state.example || null, out_dir: state.out,
    workflow: wf, mode: radio("md"), prompt: $("#prompt").value,
    fmt: $("#format").value, engine: $("#engine").value,
    narrative: $("#narrative").checked, qa_rounds: +$("#qaRounds").value,
    dry_run: $("#dryrun").checked,
  };
  $("#run").disabled=true; $("#bar").style.width="0%"; $("#results").innerHTML="";
  $("#resultsCard").style.display="none"; $("#openReport").hidden=true;
  api("/process", cfg).then(({job_id})=>listen(job_id));
};

function listen(jobId){
  const es = new EventSource("/progress/"+jobId);
  es.onmessage = ev=>{
    const d = JSON.parse(ev.data);
    if(d.type==="progress"){
      $("#bar").style.width = Math.round(d.frac*100)+"%";
      $("#status").innerHTML = /QA|sparring/.test(d.msg) ? `<span class="ai">${d.msg}</span>` : d.msg;
    } else if(d.type==="done"){
      es.close(); $("#run").disabled=false; $("#bar").style.width="100%"; render(d);
    } else if(d.type==="error"){
      es.close(); $("#run").disabled=false; $("#status").textContent="Error."; alert("Error:\n"+d.msg);
    }
  };
  es.onerror = ()=>{ es.close(); $("#run").disabled=false; };
}

function render(d){
  state.lastReport = d.out_dir;
  $("#openReport").hidden = false;
  const qa = d.qa || {};
  const qaCls = qa.checked===0 ? "" : (qa.score>=99 ? "ok" : (qa.score>=80 ? "" : "warn"));
  $("#status").innerHTML = `Done — <b>${d.title}</b> · ${d.renderer} · engine: ${d.engine}`;
  const secs = (d.sections||[]).map(s=>`<li><b>${s.heading}</b> <span class="dim">— ${s.method}</span></li>`).join("");
  const issues = (qa.issues||[]).slice(0,8).map(i=>`<li>${i.value} <span class="dim">in ${i.section}</span></li>`).join("");
  $("#results").innerHTML = `
    <div class="row"><span class="lbl">Report</span><span class="path">${d.out_path}</span></div>
    <div class="row"><span class="lbl">Source</span><span class="path">${d.artifact} <span class="dim">(reproducible)</span></span></div>
    <div class="row"><span class="lbl">QA</span>
      <span class="badge ${qaCls}">${qa.checked===0?"no numeric claims":`${qa.verified}/${qa.checked} grounded · ${qa.score}/100`}</span>
    </div>
    ${issues?`<details class="recipe"><summary>unverified numbers (${qa.issues.length})</summary><ul>${issues}</ul></details>`:""}
    <h3 class="mini">Sections</h3><ul class="sections">${secs}</ul>
    <details class="recipe"><summary>run log</summary><pre>${(d.log||[]).join("\n")}</pre></details>`;
  $("#resultsCard").style.display="block";
}
