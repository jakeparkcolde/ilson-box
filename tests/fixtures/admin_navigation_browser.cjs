// A real, isolated WebKit browser catches iframe same-document navigation.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {webkit}=require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const base=process.argv[2], token=fs.readFileSync(process.argv[3],'utf8').trim();
const views=[['업무','jobs'],['보고서','reports'],['설정','settings'],['홈','overview'],
             ['설정','settings'],['업무','jobs'],['홈','overview']];
(async()=>{
  const browser=await webkit.launch({headless:true});
  try {
    for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]){
      const context=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'});
      try {
        const page=await context.newPage();page.setDefaultTimeout(5000);
        await page.route('**/*',route=>{
          const req=route.request(),url=new URL(req.url());
          if(url.origin!==base || (!['GET','HEAD'].includes(req.method()) && url.pathname!=='/api/session'))return route.abort();
          return route.continue();
        });
        await page.goto(base+'/#token='+encodeURIComponent(token));
        await page.waitForURL('**/current/index.html?tab=home');
        const frame=page.frameLocator('#deviceFrame');
        await frame.locator('[data-page="overview"] #overview-content').waitFor({state:'visible'});
        for(const [label,view] of views){
          if(name==='mobile')await page.locator('#mNavBtn').click();
          await page.locator('#sidebar').getByRole('button',{name:label,exact:true}).click();
          await frame.locator(`[data-page="${view}"]`).waitFor({state:'visible'});
          const visible=await frame.locator('[data-page]:not([hidden])').evaluateAll(nodes=>nodes.map(n=>n.dataset.page));
          assert.deepEqual(visible,[view],`${name} ${label}`);
          assert.equal((await page.locator('#sidebar [aria-current="page"]').innerText()).trim(),label);
          assert.equal(new URL(page.url()).searchParams.get('tab'),view==='overview'?'home':view);
        }
        // Also cover a transition initiated inside the frame, then return from the parent menu.
        await frame.getByRole('button',{name:'설정 안내 보기'}).click();
        await frame.locator('[data-page="settings"]').waitFor({state:'visible'});
        await page.waitForURL('**/current/index.html?tab=settings');
        if(name==='mobile')await page.locator('#mNavBtn').click();
        await page.locator('#sidebar').getByRole('button',{name:'홈',exact:true}).click();
        await frame.locator('[data-page="overview"]').waitFor({state:'visible'});
        console.log(name+': sidebar and in-frame transitions PASS');
      } finally {await context.close();}
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1});
