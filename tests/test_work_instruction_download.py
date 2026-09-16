import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "work_instruction_download.js"


def run_node(source: str):
    script = f"const download = require({json.dumps(str(MODULE))});\n" + source
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_filename_from_content_disposition_and_fallback():
    run_node(r"""
const assert = require('assert');
assert.equal(download.filenameFromContentDisposition('attachment; filename="BSIP_IT_UOA4874_R1.xlsx"', 'fallback.xlsx'), 'BSIP_IT_UOA4874_R1.xlsx');
assert.equal(download.filenameFromContentDisposition("attachment; filename*=UTF-8''Fijaci%C3%B3n_R1.xlsx", 'fallback.xlsx'), 'Fijación_R1.xlsx');
assert.equal(download.filenameFromContentDisposition(null, 'IT-000002.xlsx'), 'IT-000002.xlsx');
assert.equal(download.filenameFromContentDisposition('attachment', 'IT-000002.xlsx'), 'IT-000002.xlsx');
""")


def test_xlsx_response_creates_blob_link_click_and_revokes_url():
    run_node(r"""
const assert = require('assert');
const calls = { blob:0, create:0, append:0, click:0, remove:0, revoke:0 };
const link = { style:{}, click(){calls.click++}, remove(){calls.remove++} };
const environment = {
  URL:{createObjectURL(blob){calls.create++; assert.equal(blob.size,4); return 'blob:test'}, revokeObjectURL(url){calls.revoke++; assert.equal(url,'blob:test')}},
  document:{createElement(tag){assert.equal(tag,'a'); return link},body:{appendChild(value){calls.append++; assert.equal(value,link)}}}
};
const response = {ok:true,status:200,headers:{get(name){return name==='content-disposition'?'attachment; filename="export.xlsx"':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}},async blob(){calls.blob++;return new Blob(['xlsx'])}};
(async()=>{const result=await download.downloadXlsxResponse(response,'fallback.xlsx',environment);assert.equal(result.filename,'export.xlsx');assert.equal(link.download,'export.xlsx');assert.equal(link.href,'blob:test');assert.deepEqual(calls,{blob:1,create:1,append:1,click:1,remove:1,revoke:1})})().catch(error=>{console.error(error);process.exit(1)});
""")


def test_ui_error_does_not_download_and_button_is_restored():
    run_node(r"""
const assert = require('assert');
let create=0,click=0,blob=0; const messages=[];
const button={disabled:false,textContent:'Exportar Excel'};
const response={ok:false,status:503,headers:{get(){return'application/json'}},async json(){return{detail:'Excel no disponible'}},async blob(){blob++;}};
const environment={URL:{createObjectURL(){create++},revokeObjectURL(){}},document:{createElement(){return{style:{},click(){click++},remove(){}}},body:{appendChild(){}}}};
(async()=>{const result=await download.exportXlsxFromUi({fetchImpl:async()=>response,url:'/exportar',fallbackFilename:'IT-000002.xlsx',button,environment,renderMessage:(kind,text)=>messages.push([kind,text])});assert.equal(result.ok,false);assert.equal(create,0);assert.equal(click,0);assert.equal(blob,0);assert.equal(button.disabled,false);assert.equal(button.textContent,'Exportar Excel');assert.deepEqual(messages.at(-1),['info','Excel no disponible'])})().catch(error=>{console.error(error);process.exit(1)});
""")


def test_ui_success_uses_fallback_and_restores_button():
    run_node(r"""
const assert=require('assert');let clicked=0,revoked=0;const button={disabled:false,textContent:'Exportar Excel'};const link={style:{},click(){clicked++},remove(){}};
const response={ok:true,status:200,headers:{get(){return null}},async blob(){return new Blob(['x'])}};
const environment={URL:{createObjectURL(){return'blob:x'},revokeObjectURL(){revoked++}},document:{createElement(){return link},body:{appendChild(){}}}};
(async()=>{const result=await download.exportXlsxFromUi({fetchImpl:async()=>response,url:'/exportar',fallbackFilename:'IT-000002.xlsx',button,environment,renderMessage:()=>{}});assert.equal(result.filename,'IT-000002.xlsx');assert.equal(link.download,'IT-000002.xlsx');assert.equal(clicked,1);assert.equal(revoked,1);assert.equal(button.disabled,false);assert.equal(button.textContent,'Exportar Excel')})().catch(error=>{console.error(error);process.exit(1)});
""")


def test_browser_dependencies_preserve_native_method_receivers():
    run_node(r"""
const assert=require('assert');let fetchThis,urlCreateThis,urlRevokeThis;
const fakeWindow={
  fetch(){fetchThis=this;return Promise.resolve('response')},
  URL:{createObjectURL(){urlCreateThis=this;return'blob:test'},revokeObjectURL(){urlRevokeThis=this}},
  document:{marker:'document'}
};
(async()=>{const deps=download.getBrowserDependencies(fakeWindow);assert.equal(await deps.fetchImpl('/export'),'response');assert.equal(fetchThis,fakeWindow);assert.equal(deps.environment.URL.createObjectURL({}),'blob:test');deps.environment.URL.revokeObjectURL('blob:test');assert.equal(urlCreateThis,fakeWindow.URL);assert.equal(urlRevokeThis,fakeWindow.URL);assert.equal(deps.environment.document,fakeWindow.document)})().catch(error=>{console.error(error);process.exit(1)});
""")
