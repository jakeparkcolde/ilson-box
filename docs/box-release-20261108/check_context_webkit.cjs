const fs = require('fs');
const {webkit} = require(process.env.PLAYWRIGHT_CORE);
(async () => {
  const browser = await webkit.launch({headless:true});
  try {
    const page = await browser.newPage();
    const origin = process.argv[2];
    await page.route('**/*', route => route.request().url().startsWith(origin + '/') ? route.continue() : route.abort());
    const token = fs.readFileSync(process.argv[3], 'utf8').trim();
    await page.goto(origin + '/approval#token=' + encodeURIComponent(token));
    await page.getByText('<img src=x onerror="window.__unsafe=1"> 고객 문의', {exact:true}).waitFor({timeout:10000});
    if (await page.evaluate(() => window.__unsafe !== undefined)) throw Error('context executed as HTML');
    console.log('real adapter context rendered as text');
  } finally { await browser.close(); }
})().catch(e => {console.error(e.message); process.exitCode=1;});
