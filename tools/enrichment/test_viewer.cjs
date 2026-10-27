// Offline UI smoke test with invented text and a fake file picker.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(__dirname + '/label.html', 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {value:'',textContent:'',disabled:false, handlers:{}, addEventListener(name, fn){this.handlers[name]=fn;}});
  return elements.get(id);
}
let written = '';
const context = {document:{getElementById:element}, window:{addEventListener(){}, async showSaveFilePicker(){return {async createWritable(){return {async write(s){written=s;},async close(){}};}};}}, confirm:()=>true, console};
vm.createContext(context);
vm.runInContext(script,context);
(async()=>{
  const sample={version:1,dataset_id:'invented-1',cases:[{id:'dev-1',split:'dev',text:'🏠 pool'},{id:'test-1',split:'test',text:'Nothing stated.'}]};
  await element('sample').handlers.change({target:{files:[{async text(){return JSON.stringify(sample);}}]}});
  assert.equal(element('remark').textContent,'🏠 pool');
  element('editor').value=JSON.stringify([{kind:'facet',group:'exterior_lot',value:'pool',polarity:'affirmed',temporality:'current',start:2,end:6,quote:'pool'}]);
  element('editor').handlers.input();
  element('next').handlers.click();
  assert.equal(element('remark').textContent,'Nothing stated.');
  element('saveCase').handlers.click();
  await element('saveFile').handlers.click();
  const saved=JSON.parse(written);
  assert.equal(saved.dataset_id,'invented-1');
  assert.equal(saved.labels.length,2);
  assert.deepEqual(saved.labels[0].annotations[0],{kind:'facet',group:'exterior_lot',value:'pool',polarity:'affirmed',temporality:'current',start:2,end:6,quote:'pool'});
  assert.deepEqual(saved.labels[1].annotations,[]);
  element('previous').handlers.click();
  element('editor').value=JSON.stringify([{kind:'facet',group:'exterior_lot',value:'pool',polarity:'affirmed',temporality:'current',start:1,end:6,quote:'pool'}]);
  element('editor').handlers.input();
  element('next').handlers.click();
  assert.match(element('status').textContent,/valid code-point/);
  assert.equal(element('remark').textContent,'🏠 pool');
  assert.match(html,/connect-src 'none'/);
  console.log('viewer smoke test passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
