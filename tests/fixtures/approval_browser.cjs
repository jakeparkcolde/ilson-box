const fs = require('fs');
const { webkit } = require(process.env.PLAYWRIGHT_CORE);
(async () => {
  const browser = await webkit.launch({headless: true});
  try {
    const page = await browser.newPage();
    page.on('dialog', dialog => dialog.accept());
    const token = fs.readFileSync(process.argv[3], 'utf8').trim();
    await page.goto(process.argv[2] + '/approval#token=' + encodeURIComponent(token));
    await page.getByText('<img src=x onerror="window.__unsafe=1"> 고객 문의', {exact:true}).waitFor();
    await page.getByText('<script>window.__unsafe=2</script>', {exact:true}).waitFor();
    await page.getByText('<b>악성 제목</b>', {exact:true}).waitFor();
    if (await page.evaluate(() => window.__unsafe !== undefined)) throw new Error('user input executed as HTML');
    await page.locator('#name').fill('draft.md');
    await page.getByRole('button', {name:'대기함에 추가'}).click();
    await page.getByText('확인할 초안 내용').waitFor();
    const draftCard = page.locator('article').filter({hasText:'확인할 초안 내용'});
    await draftCard.getByRole('button', {name:'승인', exact:true}).click();
    await page.getByText('상태: 성공').waitFor();
    console.log('approval WebKit PASS');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode=1; });
