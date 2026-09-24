"""Reader regression against Vite: python tests/pdfReader.browser.py [base URL].

Requires Python Playwright + Chromium. Uses a generated two-column PDF and an
isolated React harness; no user library, backend, or AI connection is touched.
"""
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / '.test-pdf-reader'
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5194'


def fixture_pdf():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>']
    for page in (1, 2):
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents {4 if page == 1 else 6} 0 R >>'.encode())
        commands = []
        for x, col in [(48, 'Left'), (330, 'Right')]:
            for i in range(24):
                commands.append(f'BT /F1 12 Tf {x} {730-i*23} Td ({col} column page {page} line {i+1:02d} text.) Tj ET')
        stream = '\n'.join(commands).encode()
        objects.append(b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream')
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    data = b'%PDF-1.7\n'
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(data)
    data += f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data + f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode()


HARNESS.mkdir(exist_ok=True)
(HARNESS / 'index.html').write_text('<div id="root"></div><script type="module" src="./main.tsx"></script>', encoding='utf-8')
(HARNESS / 'main.tsx').write_text('''
import React from 'react';
import {createRoot} from 'react-dom/client';
import PdfReader from '/src/components/PdfReader';
import {WorkspaceContext} from '/src/workspaceContext';
import {ToastProvider} from '/src/components/ui/Toast';
import {ConfirmProvider,useConfirm} from '/src/components/ui/ConfirmDialog';
import {Drawer} from '/src/components/ui/Drawer';
import {TranslationModelSettings} from '/src/components/TranslationModelSettings';
import {DocumentModelSettings} from '/src/components/DocumentModelSettings';
import '/src/design-tokens.css';
import '/src/index.css';
import '/src/workspace.css';
window.translationCalls=[];window.pendingTranslations=[];
window.documentState={status:'idle',mode:'auto',total_pages:0,completed_pages:0,ocr_pages:0,has_markdown:false,model_name:'',error:'',index_status:''};
window.conversions=[];
const api = {
 documentModels: async()=>({ocr:[{id:44,name:'Vision OCR',provider:'Test',supports_images:true}],rerank:[{id:55,name:'Ranker',provider:'Test'}],rerank_llm:[{id:44,name:'Vision OCR',provider:'Test',supports_images:true}]}),
 documentStatus: async()=>window.documentState,
 documentMarkdown: async()=>({markdown:'# Recognized paper\\n\\n## 第 1 页\\n\\n| A | B |\\n|---|---|\\n| 1 | 2 |\\n\\n[查看原始页面](page-1.png)'}),
 convertDocument: async(id,mode,force)=>{
   window.conversions.push({id,mode,force});
   if(window.failConversion) throw new Error('synthetic conversion failure');
   return window.documentState={...window.documentState,status:'running',mode,total_pages:2,completed_pages:1,ocr_pages:1,model_name:'Vision OCR'};
 },
 cancelDocument: async()=>window.documentState={...window.documentState,status:'cancelled'},
 prepareReading: async () => ({status:'ready', message:'就绪'}), createConversation: () => new Promise(() => {}),
 chatModels: async () => {
   if(window.failModelLoad) throw new Error('synthetic model load failure');
   return [11,22,33].map(id=>({id,name:id===11?'Chat default':`Translator ${id}`,provider:'Test provider',is_default:id===11}));
 },
 listSettings: async () => ({translation_model_config_id:localStorage.getItem('pdf-translation-test-pref') || '',ocr_model_config_id:localStorage.getItem('ocr_model_config_id') || '',rerank_model_config_id:localStorage.getItem('rerank_model_config_id') || '',rerank_mode:localStorage.getItem('rerank_mode') || '',rerank_llm_model_config_id:localStorage.getItem('rerank_llm_model_config_id') || ''}),
 putSetting: async (key,value) => {
   if(window.failModelSave) throw new Error('synthetic model save failure');
   localStorage.setItem(key==='translation_model_config_id'?'pdf-translation-test-pref':key,value); return {key,value};
 },
 translateSelection: async (paper,text,target,model,signal) => {
   window.translationCalls.push({paper,text,target,model});
   if(window.delayTranslation) await new Promise(resolve=>window.pendingTranslations.push(resolve));
   if(window.failTranslation) throw new Error('synthetic translation failure');
   return {text:`Translated [${model || 'default'}] ${target}: ${text}`,model:`model-${model || 'default'}`};
 }
};
window.savedExcerpt = null; window.readerClosed = false;
const initialExcerpts = [1,2].map(id=>({id,quote:`Excerpt ${id}`,page:id,note:`Remark ${id}`,tags:[]}));
function Harness() {
const [excerpts,setExcerpts] = React.useState(initialExcerpts);
return <PdfReader paperId={1} title="PDF selection regression" notes={[]} excerpts={excerpts} initialPage={1}
onSaveExcerpt={async (text,page) => {
  if(window.failExcerpt) throw new Error('synthetic save failure');
  if(window.delayExcerpt) await new Promise(resolve=>window.finishExcerpt=resolve);
  window.savedExcerpt={text,page}; return true;
}}
onSaveExcerptNote={async(id,note)=>{
  if(window.delayRemark) await new Promise(resolve=>window.finishRemark=resolve);
  setExcerpts(items=>items.map(e=>e.id===id?{...e,note}:e)); return true;
}}
onCreateNote={async(payload)=>{
  if(window.delayNote) await new Promise(resolve=>window.finishNote=resolve);
  window.savedNote=payload; return true;
}} onRefreshNotes={async()=>{}}
onProgress={()=>{}} onOpenPaper={()=>{}} onClose={()=>{window.readerClosed=true;}} />
}
function DialogHarness() {
 const [open,setOpen]=React.useState(false); const confirm=useConfirm();
 const [settingsOpen,setSettingsOpen]=React.useState(false);
 window.openTestDrawer=()=>setOpen(true);
 window.openTranslationSettings=()=>setSettingsOpen(true);
 return <><Drawer open={open} title="Nested dialog test" onClose={()=>{window.drawerClosed=true;setOpen(false);}}>
   <button onClick={()=>void confirm({title:'Nested confirmation',message:'Keep the drawer open when cancelling.'})}>Open confirmation</button>
 </Drawer><Drawer open={settingsOpen} title="Translation settings" onClose={()=>setSettingsOpen(false)}><TranslationModelSettings /><DocumentModelSettings /></Drawer></>;
}
createRoot(document.getElementById('root')).render(<React.StrictMode><WorkspaceContext.Provider value={{base:'/api', api, workspace:{id:'pdf-test'}} as any}><ToastProvider><ConfirmProvider><Harness /><DialogHarness />
</ConfirmProvider></ToastProvider></WorkspaceContext.Provider></React.StrictMode>);
''', encoding='utf-8')

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1.5)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/api/papers/1/file', lambda route: route.fulfill(body=fixture_pdf(), content_type='application/pdf'))
        page.goto(URL + '/.test-pdf-reader/index.html')
        page.wait_for_function("document.querySelectorAll('.textLayer span').length === 48")
        page.get_by_role('button', name='收起侧栏', exact=True).click()

        def ready():
            page.wait_for_function("document.querySelectorAll('.textLayer span').length === 48 && !document.body.innerText.includes('渲染中')")

        def geometry(scale):
            ready()
            page.locator('.textLayer').evaluate('(e)=>e.closest(".overflow-auto").scrollTo(0,0)')
            result = page.evaluate('''() => {
              const span = document.querySelector('.textLayer span');
              const layer = document.querySelector('.textLayer');
              const canvas = document.querySelector('canvas');
              const r = span.getBoundingClientRect(), c = canvas.getBoundingClientRect();
              return {font:parseFloat(getComputedStyle(span).fontSize), left:r.left-c.left,
                layerWidth:layer.getBoundingClientRect().width, canvasWidth:c.width,
                color:getComputedStyle(span,'::selection').color,
                background:getComputedStyle(span,'::selection').backgroundColor};
            }''')
            assert abs(result['font'] - 12*scale) < .1, result
            assert abs(result['left'] - 48*scale) < .2, result
            assert abs(result['layerWidth']-result['canvasWidth']) < .1, result
            assert result['color'] == 'rgba(0, 0, 0, 0)', result
            assert result['background'] == 'rgba(67, 126, 183, 0.24)', result
            return result

        def drag(start, end, pending=False):
            boxes = page.locator('.textLayer span').evaluate_all('(spans) => spans.map(s => {const r=s.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})')
            a, b = boxes[start], boxes[end]
            page.mouse.move(a['x']+(1 if start <= end else a['w']-1), a['y']+a['h']/2)
            page.mouse.down()
            page.mouse.move(b['x']+(b['w']-1 if start <= end else 1), b['y']+b['h']/2, steps=16)
            assert page.get_by_role('button', name='存为摘录', exact=True).count() == 0
            page.mouse.up()
            page.get_by_role('button', name='保存中…' if pending else '存为摘录', exact=True).wait_for()
            return page.evaluate('window.getSelection().toString()')

        results = [geometry(1.2)]
        # Reproduce the old integration defect without changing the source:
        # absent PDFViewer variables must produce the wrong glyph hit-box size.
        baseline = page.evaluate('''() => {
          const wrapper = document.querySelector('.pdf-reader-page');
          const scale = wrapper.style.getPropertyValue('--total-scale-factor');
          wrapper.style.removeProperty('--total-scale-factor');
          const font = parseFloat(getComputedStyle(document.querySelector('.textLayer span')).fontSize);
          wrapper.style.setProperty('--total-scale-factor', scale);
          return font;
        }''')
        assert abs(baseline - 14.4) > .1, baseline
        selected = drag(0, 2)
        assert 'Left column page 1 line 01' in selected and 'line 03' in selected and 'Right' not in selected, selected
        page.screenshot(path=str(HARNESS / 'selection.png'))
        page.get_by_role('button', name='存为摘录', exact=True).click()
        page.wait_for_function('window.savedExcerpt !== null')
        saved = page.evaluate('window.savedExcerpt')
        assert saved['page'] == 1 and 'line 03' in saved['text'], saved
        assert not page.evaluate('window.getSelection().toString()')
        selected = drag(26, 24)
        assert 'Right column page 1 line 01' in selected and 'Left' not in selected, selected
        page.keyboard.press('Escape')
        assert not page.evaluate('window.readerClosed')
        assert not page.evaluate('window.getSelection().toString()')
        for name, scale in [('放大',1.44), ('放大',1.73), ('缩小',1.44)]:
            page.get_by_role('button', name=name, exact=True).click()
            results.append(geometry(scale))
            assert 'Left column page 1' in drag(0,1)
        page.get_by_role('button', name='下一页', exact=True).click()
        ready()
        assert page.locator('.textLayer').inner_text().startswith('Left column page 2')
        assert 'page 2' in drag(0,1)
        # Scrolling fully past the selection must hide its floating controls.
        page.locator('.textLayer').evaluate('(e)=> {const s=e.closest(".overflow-auto");s.scrollTop=500;}')
        page.get_by_role('button', name='存为摘录', exact=True).wait_for(state='hidden')
        # Rapid zoom/page changes must not append a stale layer or duplicate text.
        for i in range(6):
            page.get_by_role('button', name='放大' if i%2==0 else '缩小', exact=True).click()
        page.get_by_role('button', name='上一页', exact=True).click()
        ready()
        assert page.locator('.textLayer').inner_text().startswith('Left column page 1')

        # Zoom keeps the page point at the viewport centre instead of jumping up.
        page.locator('.textLayer').evaluate('(e)=>e.closest(".overflow-auto").scrollTop=300')
        centre = '''() => {const r=document.querySelector('.pdf-reader-page').getBoundingClientRect();
          const s=document.querySelector('.textLayer').closest('.overflow-auto');
          return (s.getBoundingClientRect().top+s.clientHeight/2-r.top)/r.height;}'''
        before = page.evaluate(centre)
        page.get_by_role('button', name='放大', exact=True).click()
        ready()
        assert abs(before-page.evaluate(centre)) < .005

        # Blank/decimal input must not silently navigate to page 1.
        page.get_by_role('button', name='下一页', exact=True).click()
        ready()
        for invalid in ['', '1.5', 'abc', '0']:
            page.get_by_role('textbox', name='页码', exact=True).fill(invalid)
            page.get_by_role('textbox', name='页码', exact=True).press('Enter')
            assert page.get_by_role('textbox', name='页码', exact=True).input_value() == '2'
        page.get_by_role('textbox', name='页码', exact=True).focus()
        page.keyboard.press('Escape')
        assert not page.evaluate('window.readerClosed')

        # A real canvas render exception is visible and can be retried in place.
        page.evaluate('''() => {const original=CanvasRenderingContext2D.prototype.save;
          CanvasRenderingContext2D.prototype.save=function(){
            CanvasRenderingContext2D.prototype.save=original;
            throw new Error('synthetic render failure');};}''')
        page.get_by_role('button', name='上一页', exact=True).click()
        page.get_by_role('button', name='重试当前页', exact=True).wait_for()
        page.get_by_role('button', name='重试当前页', exact=True).click()
        ready()
        assert page.locator('.textLayer').inner_text().startswith('Left column page 1')

        # An old save must not clear a newer text selection.
        page.locator('.textLayer').evaluate('(e)=>e.closest(".overflow-auto").scrollTo(0,0)')
        drag(0,1)
        page.evaluate('window.delayExcerpt=true')
        page.get_by_role('button', name='存为摘录', exact=True).click()
        page.wait_for_function('!!window.finishExcerpt')
        new_selection = drag(3,4,pending=True)
        page.evaluate('window.delayExcerpt=false;window.finishExcerpt()')
        page.get_by_role('button', name='存为摘录', exact=True).wait_for()
        assert page.evaluate('window.getSelection().toString()') == new_selection
        page.evaluate('window.failExcerpt=true')
        page.get_by_role('button', name='存为摘录', exact=True).click()
        page.get_by_text('synthetic save failure', exact=True).wait_for()
        assert page.evaluate('window.getSelection().toString()') == new_selection
        page.evaluate('window.failExcerpt=false')
        page.keyboard.press('Escape')

        # Slow saves preserve anything typed after submission.
        page.get_by_role('button', name='AI 伴读 / 笔记', exact=True).click()
        page.get_by_role('button', name='笔记与摘录', exact=True).click()
        page.get_by_role('textbox', name='笔记内容', exact=True).fill('submitted note')
        page.evaluate('window.delayNote=true')
        page.get_by_role('button', name='保存笔记', exact=True).click()
        page.wait_for_function('!!window.finishNote')
        page.get_by_role('textbox', name='笔记内容', exact=True).fill('newer note while saving')
        page.evaluate('window.delayNote=false;window.finishNote()')
        page.get_by_role('button', name='保存笔记', exact=True).wait_for()
        assert page.get_by_role('textbox', name='笔记内容', exact=True).input_value() == 'newer note while saving'
        page.get_by_role('button', name='保存笔记', exact=True).click()
        page.wait_for_function("document.querySelector('[aria-label=笔记内容]').value === ''")

        page.get_by_role('button', name='编辑备注', exact=True).first.click()
        page.get_by_role('textbox', name='摘录备注', exact=True).fill('unsaved remark')
        page.get_by_role('button', name='编辑备注', exact=True).click()
        page.get_by_role('alertdialog').wait_for()
        page.keyboard.press('Shift+Tab')
        assert page.get_by_role('alertdialog').get_by_role('button', name='丢弃并切换', exact=True).evaluate('(e)=>e===document.activeElement')
        page.keyboard.press('Tab')
        assert page.get_by_role('alertdialog').get_by_role('button', name='取消', exact=True).evaluate('(e)=>e===document.activeElement')
        page.get_by_role('alertdialog').get_by_role('button', name='取消', exact=True).click()
        assert page.get_by_role('textbox', name='摘录备注', exact=True).input_value() == 'unsaved remark'
        page.evaluate('window.delayRemark=true')
        page.get_by_role('button', name='保存备注', exact=True).click()
        page.wait_for_function('!!window.finishRemark')
        assert page.get_by_role('button', name='编辑备注', exact=True).is_disabled()
        page.get_by_role('textbox', name='摘录备注', exact=True).fill('newer remark while saving')
        page.evaluate('window.delayRemark=false;window.finishRemark()')
        page.get_by_role('button', name='保存备注', exact=True).wait_for()
        assert page.get_by_role('textbox', name='摘录备注', exact=True).input_value() == 'newer remark while saving'
        page.get_by_role('button', name='编辑备注', exact=True).click()
        page.get_by_role('alertdialog').get_by_role('button', name='丢弃并切换', exact=True).click()
        assert page.get_by_role('textbox', name='摘录备注', exact=True).input_value() == 'Remark 2'

        # Loading failures have their own retry; no full app restart is needed.
        page.unroute('**/api/papers/1/file')
        fail_load = [True]
        def serve(route):
            if fail_load[0]: route.fulfill(status=503,body='temporary failure')
            else: route.fulfill(body=fixture_pdf(),content_type='application/pdf')
        page.route('**/api/papers/1/file',serve)
        page.reload()
        page.get_by_role('button', name='重新打开 PDF', exact=True).wait_for()
        assert page.get_by_role('textbox', name='页码', exact=True).is_disabled()
        fail_load[0] = False
        page.get_by_role('button', name='重新打开 PDF', exact=True).click()
        ready()
        page.evaluate('window.openTestDrawer()')
        page.get_by_role('button',name='Open confirmation',exact=True).click()
        page.get_by_role('alertdialog',name='Nested confirmation').wait_for()
        page.keyboard.press('Escape')
        page.get_by_role('alertdialog').wait_for(state='hidden')
        assert not page.evaluate('!!window.drawerClosed')
        assert not page.evaluate('window.readerClosed')
        page.get_by_role('button',name='关闭抽屉',exact=True).click()
        # Narrow layout and light theme retain a readable, reachable toolbar.
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button', name='收起侧栏', exact=True).click()
        page.evaluate("document.documentElement.classList.remove('dark');document.documentElement.dataset.theme='light'")
        page.get_by_role('button', name='缩小', exact=True).click()
        ready()
        drag(0,1)
        toolbar = page.get_by_role('button', name='存为摘录', exact=True).locator('..').bounding_box()
        assert toolbar['x'] >= 0 and toolbar['x']+toolbar['width'] <= 390, toolbar
        selected_bounds = page.evaluate('''() => {const r=window.getSelection().getRangeAt(0).getBoundingClientRect();return {top:r.top,bottom:r.bottom};}''')
        assert toolbar['y']+toolbar['height'] <= selected_bounds['top'] or toolbar['y'] >= selected_bounds['bottom'], (toolbar,selected_bounds)
        page.screenshot(path=str(HARNESS / 'narrow-selection.png'))

        # Translation lives in a separate movable window, with its own saved model.
        page.set_viewport_size({'width':1440,'height':1000})
        page.keyboard.press('Escape')
        page.get_by_role('button',name='存为摘录',exact=True).wait_for(state='hidden')
        page.locator('.textLayer').evaluate('(e)=>e.closest(".overflow-auto").scrollTo(0,0)')
        drag(0,1)
        page.get_by_role('button',name='翻译',exact=True).click()
        popup = page.get_by_role('dialog',name='划词翻译',exact=True)
        popup.wait_for()
        popup.get_by_text('Translated [default]',exact=False).wait_for()
        assert page.get_by_role('button',name='AI 伴读 / 笔记',exact=True).is_visible()
        assert page.locator('.reading-companion .translation-content').count() == 0
        popup.get_by_role('combobox',name='翻译模型',exact=True).select_option('22')
        popup.get_by_text('Translated [22]',exact=False).wait_for()
        assert page.evaluate("localStorage.getItem('pdf-translation-test-pref')") == '22'
        popup.get_by_role('combobox',name='翻译目标语言',exact=True).select_option('English')
        popup.get_by_text('Translated [22] English:',exact=False).wait_for()
        page.context.grant_permissions(['clipboard-read','clipboard-write'])
        popup.get_by_role('button',name='复制译文',exact=True).click()
        assert 'Translated [22] English:' in page.evaluate('navigator.clipboard.readText()')
        before = popup.bounding_box()
        heading = popup.locator('header').bounding_box()
        page.mouse.move(heading['x']+60,heading['y']+20)
        page.mouse.down(); page.mouse.move(heading['x']+120,heading['y']+80,steps=8); page.mouse.up()
        after = popup.bounding_box()
        assert abs(after['x']-before['x']) > 30 and abs(after['y']-before['y']) > 30
        page.screenshot(path=str(HARNESS / 'translation-desktop.png'))
        page.keyboard.press('Escape')
        popup.wait_for(state='hidden')
        assert not page.evaluate('window.readerClosed')

        page.evaluate('window.openTranslationSettings()')
        settings = page.get_by_role('dialog',name='Translation settings',exact=True)
        settings.get_by_role('combobox',name='翻译模型',exact=True).wait_for()
        page.wait_for_function("document.querySelector('[aria-label=翻译模型]').value === '22'")
        settings.get_by_role('combobox',name='翻译模型',exact=True).select_option('33')
        page.wait_for_function("localStorage.getItem('pdf-translation-test-pref') === '33'")
        page.get_by_role('button',name='关闭抽屉',exact=True).click()
        drag(2,3)
        page.get_by_role('button',name='翻译',exact=True).click()
        popup.get_by_text('Translated [33]',exact=False).wait_for()
        assert popup.get_by_role('combobox',name='翻译模型',exact=True).input_value() == '33'

        page.evaluate('window.failModelSave=true')
        popup.get_by_role('combobox',name='翻译模型',exact=True).select_option('22')
        popup.get_by_text('synthetic model save failure',exact=False).wait_for()
        assert popup.get_by_role('combobox',name='翻译模型',exact=True).input_value() == '33'
        page.evaluate('window.failModelSave=false;window.failTranslation=true')
        popup.get_by_role('button',name='重新翻译',exact=True).click()
        popup.get_by_text('synthetic translation failure',exact=True).wait_for()
        page.evaluate('window.failTranslation=false')
        popup.get_by_role('button',name='重试翻译',exact=True).click()
        popup.get_by_text('Translated [33]',exact=False).wait_for()

        # Ignore a late response after target change, even if transport ignores abort.
        page.evaluate('window.delayTranslation=true')
        popup.get_by_role('combobox',name='翻译目标语言',exact=True).select_option('English')
        page.wait_for_function('window.pendingTranslations.length > 0')
        page.evaluate('window.delayTranslation=false')
        popup.get_by_role('combobox',name='翻译目标语言',exact=True).select_option('中文')
        popup.get_by_text('Translated [33] 中文:',exact=False).wait_for()
        page.evaluate('window.pendingTranslations.splice(0).forEach(resolve=>resolve())')
        assert 'Translated [33] 中文:' in popup.inner_text()
        page.evaluate('window.delayTranslation=true')
        popup.get_by_role('button',name='重新翻译',exact=True).click()
        page.wait_for_function('window.pendingTranslations.length > 0')
        popup.get_by_role('button',name='关闭翻译',exact=True).click()
        page.evaluate('window.delayTranslation=false')
        drag(4,5)
        page.get_by_role('button',name='翻译',exact=True).click()
        popup.get_by_text('Translated [33]',exact=False).wait_for()
        page.evaluate('window.pendingTranslations.splice(0).forEach(resolve=>resolve())')
        assert 'line 05' in popup.inner_text() and 'line 03' not in popup.inner_text()
        popup.get_by_role('button',name='关闭翻译',exact=True).click()

        page.evaluate('window.failModelLoad=true')
        count = page.evaluate('window.translationCalls.length')
        drag(0,1)
        page.get_by_role('button',name='翻译',exact=True).click()
        popup.get_by_text('synthetic model load failure',exact=False).wait_for()
        assert page.evaluate('window.translationCalls.length') == count
        page.evaluate('window.failModelLoad=false')
        popup.get_by_role('button',name='重新加载模型',exact=True).click()
        popup.get_by_text('Translated [33]',exact=False).wait_for()
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_function("document.querySelector('.translation-popover').getBoundingClientRect().right <= innerWidth")
        bounds = popup.bounding_box()
        assert bounds['x'] >= 0 and bounds['y'] >= 0 and bounds['y']+bounds['height'] <= 844
        page.screenshot(path=str(HARNESS / 'translation-narrow.png'))
        popup.get_by_role('button',name='关闭翻译',exact=True).click()
        page.set_viewport_size({'width':1440,'height':1000})
        page.get_by_role('button',name='OCR / Markdown',exact=True).click()
        conversion = page.get_by_role('dialog',name='OCR 与 Markdown',exact=True)
        conversion.get_by_text('尚未转换',exact=True).wait_for()
        conversion.get_by_role('button',name='配置 OCR 模型',exact=True).click()
        conversion.get_by_label('OCR 模型',exact=True).select_option('44')
        page.wait_for_function("localStorage.getItem('ocr_model_config_id')==='44'")
        conversion.get_by_label('转换方式',exact=True).select_option('ocr')
        page.evaluate('window.failConversion=true')
        conversion.get_by_role('button',name='开始转换',exact=True).click()
        conversion.get_by_text('synthetic conversion failure',exact=False).wait_for()
        page.evaluate('window.failConversion=false')
        conversion.get_by_role('button',name='开始转换',exact=True).click()
        conversion.get_by_role('button',name='停止转换',exact=True).wait_for()
        assert page.evaluate('window.conversions[1].mode') == 'ocr'
        page.keyboard.press('Escape')
        conversion.wait_for(state='hidden')
        assert not page.evaluate('window.readerClosed')
        page.get_by_role('button',name='OCR / Markdown',exact=True).click()
        conversion.get_by_role('button',name='停止转换',exact=True).click()
        conversion.get_by_text('已停止',exact=False).wait_for()
        conversion.get_by_role('button',name='继续转换',exact=True).click()
        page.evaluate("window.documentState={...window.documentState,status:'ready',completed_pages:2,ocr_pages:2,has_markdown:true,index_status:'ready'}")
        conversion.get_by_role('heading',name='Recognized paper').wait_for()
        assert conversion.get_by_role('link',name='查看原始页面').get_attribute('href') == '/api/papers/1/document/pages/1'
        assert conversion.get_by_role('link',name='下载 Markdown 与原图').get_attribute('href').endswith('?bundle=true')
        page.screenshot(path=str(HARNESS / 'ocr-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        bounds = conversion.bounding_box()
        assert bounds['x'] >= 0 and bounds['x']+bounds['width'] <= 391
        page.screenshot(path=str(HARNESS / 'ocr-narrow.png'))
        conversion.get_by_role('button',name='关闭文档转换').click()
        page.set_viewport_size({'width':1440,'height':1000})
        page.evaluate('window.openTranslationSettings()')
        settings = page.get_by_role('dialog',name='Translation settings')
        settings.get_by_label('OCR 模型',exact=True).wait_for()
        assert settings.get_by_label('OCR 模型',exact=True).input_value() == '44'
        settings.get_by_label('重排序方式',exact=True).select_option('dedicated')
        settings.get_by_label('重排序模型',exact=True).select_option('55')
        page.wait_for_function("localStorage.getItem('rerank_model_config_id')==='55'")
        settings.get_by_label('重排序方式',exact=True).select_option('llm')
        assert settings.get_by_label('用于重排序的大模型',exact=True).input_value() == ''
        settings.get_by_label('用于重排序的大模型',exact=True).select_option('44')
        page.wait_for_function("localStorage.getItem('rerank_llm_model_config_id')==='44'")
        assert settings.get_by_label('OCR 模型',exact=True).input_value() == '44'
        settings.get_by_label('重排序方式',exact=True).select_option('off')
        settings.get_by_label('用于重排序的大模型',exact=True).wait_for(state='hidden')
        settings.get_by_label('重排序方式',exact=True).select_option('dedicated')
        page.wait_for_function("document.querySelector('[aria-label=重排序模型]').value==='55'")
        settings.get_by_label('重排序方式',exact=True).select_option('llm')
        page.wait_for_function("document.querySelector('[aria-label=用于重排序的大模型]').value==='44'")
        page.evaluate('window.failModelSave=true')
        settings.get_by_label('重排序方式',exact=True).select_option('off')
        settings.get_by_text('synthetic model save failure',exact=False).wait_for()
        assert settings.get_by_label('重排序方式',exact=True).input_value() == 'llm'
        page.evaluate('window.failModelSave=false')
        page.screenshot(path=str(HARNESS / 'rerank-llm-settings.png'))
        assert not errors, errors
        print(json.dumps({'passed':True,'oldFontSize':baseline,'geometry':results,'saved':saved}, ensure_ascii=False))
        browser.close()
finally:
    # Keep only the screenshot as local QA evidence.
    (HARNESS / 'main.tsx').unlink(missing_ok=True)
    (HARNESS / 'index.html').unlink(missing_ok=True)
