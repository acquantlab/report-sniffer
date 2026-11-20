// node bench/print_pdf.js IN.html OUT.pdf: a report printed to PDF by Chromium (used by bench/esef.py)
const { chromium } = require("playwright");
(async () => {
  const [src, out] = process.argv.slice(2);
  const b = await chromium.launch();
  const page = await b.newPage();
  await page.goto("file://" + src, { waitUntil: "load", timeout: 600000 });
  await page.pdf({ path: out, preferCSSPageSize: true, printBackground: true, timeout: 600000 });
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
