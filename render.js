#!/usr/bin/env node
/**
 * stockgen headless renderer.
 * Injects window.STOCKGEN params BEFORE the sketch loads, then captures
 * `frames` deterministic frames (noLoop + redraw) to a dir as PNGs.
 *
 * Usage:
 *   node render.js <sketch.html> --out <dir> --width 3840 --height 2160 \
 *        --frames 300 --seed 42
 */
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');

function parseArgs() {
  const a = process.argv.slice(2);
  const o = { input: null, out: './frames', width: 3840, height: 2160, frames: 300, seed: 42 };
  for (let i = 0; i < a.length; i++) {
    if (a[i].startsWith('--')) {
      const k = a[i].slice(2), v = a[i + 1];
      if (k in o && v !== undefined) { o[k] = isNaN(Number(v)) ? v : Number(v); i++; }
    } else if (!o.input) o.input = a[i];
  }
  if (!o.input) { console.error('need sketch.html'); process.exit(1); }
  return o;
}

async function main() {
  const o = parseArgs();
  const inputPath = path.resolve(o.input);
  if (!fs.existsSync(inputPath)) { console.error('not found: ' + inputPath); process.exit(1); }
  fs.mkdirSync(o.out, { recursive: true });

  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox',
           '--disable-dev-shm-usage', '--allow-file-access-from-files',
           '--enable-webgl', '--use-gl=angle', '--use-angle=metal'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: o.width, height: o.height, deviceScaleFactor: 1 });

  // inject params BEFORE any page script runs
  await page.evaluateOnNewDocument((params) => { window.STOCKGEN = params; },
    { seed: o.seed, width: o.width, height: o.height, frames: o.frames });

  await page.goto('file://' + inputPath, { waitUntil: 'networkidle0', timeout: 30000 });
  await page.waitForSelector('canvas', { timeout: 10000 });

  let deterministic = false;
  try {
    await page.waitForFunction('window._p5Ready === true', { timeout: 8000 });
    deterministic = true;
  } catch { await new Promise(r => setTimeout(r, 2000)); }

  const t0 = Date.now();
  for (let i = 0; i < o.frames; i++) {
    if (deterministic) {
      await page.evaluate(() => { redraw(); });
      await new Promise(r => setTimeout(r, 8));
    }
    const fp = path.join(o.out, `frame-${String(i).padStart(5, '0')}.png`);
    // Use page.screenshot with clip for WEBGL compatibility (canvas.screenshot
    // returns black for WEBGL contexts in headless Chromium)
    await page.screenshot({ path: fp, type: 'png',
      clip: { x: 0, y: 0, width: o.width, height: o.height } });
    if (i % 30 === 0 || i === o.frames - 1) {
      const pct = ((i + 1) / o.frames * 100).toFixed(0);
      process.stdout.write(`\r  seed ${o.seed}: frame ${i + 1}/${o.frames} (${pct}%) ${((Date.now()-t0)/1000).toFixed(0)}s`);
    }
  }
  process.stdout.write('\n');
  await browser.close();
}
main().catch(e => { console.error('render error:', e.message); process.exit(1); });
