import json
from pathlib import Path
import shutil
import subprocess

import pytest


MODULE = (Path(__file__).parents[1] / "material_ui/static/template-updates.js").as_uri()


@pytest.mark.parametrize("accept", [True, False])
def test_template_prompt_before_render_saves_choice_once_and_rejects_stale_editor(accept):
    if not shutil.which("node"):
        pytest.skip("Node fehlt")
    script = r'''
import assert from 'node:assert/strict';
import {createTemplateUpdateController} from MODULE;
let text = 'v1';
let saved = text;
let newest = 'v2';
let prompts = 0;
const state = {session:1,qmdPath:'a.qmd',course:{kursMode:false}};
const api = async (url, options) => {
  if (!options) return {offer:saved.includes(`reviewed:${newest}:`) ? null : {release:newest,version:2,currentVersion:1}};
  const data = JSON.parse(options.body);
  assert.equal(data.accept, ACCEPT);
  return {text:`${data.text} reviewed:${data.release}:${data.accept}`};
};
const controller = createTemplateUpdateController({state,api,getEditorText:()=>text,setEditorText:value=>{text=value},
  flushPendingSave:async()=>{},
  saveDocument:async()=>{saved=text},
  confirmUpdate:async()=>{prompts++;return ACCEPT}});
assert.deepEqual(await Promise.all([controller.beforeRender(),controller.beforeRender()]), [true,true]);
assert.equal(prompts,1);
assert.equal(saved,text);
assert.ok(saved.includes(`reviewed:v2:${ACCEPT}`));
assert.equal(await controller.beforeRender(),true);
assert.equal(prompts,1);
newest='v3';
assert.equal(await controller.beforeRender(),true);
assert.equal(prompts,2);

// Edits made while the API response is in flight must never be replaced.
let resolvePost;
let confirmStarted;
const reached = new Promise(resolve=>{confirmStarted=resolve});
const stale = createTemplateUpdateController({state,getEditorText:()=>text,setEditorText:()=>{throw Error('overwritten')},
  flushPendingSave:async()=>{},confirmUpdate:()=>true,
  api:async(url,options)=>{
    if (!options) return {offer:{release:'v4',version:4,currentVersion:1}};
    confirmStarted();
    return new Promise(resolve=>{resolvePost=resolve});
  }});
const pending = stale.beforeRender();
await reached;
text+=' newer edit';
resolvePost({text:'outdated answer'});
assert.equal(await pending,false);
assert.ok(text.endsWith('newer edit'));
'''.replace("MODULE", json.dumps(MODULE)).replace("ACCEPT", str(accept).lower())
    result = subprocess.run(["node", "--input-type=module", "-e", script], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
