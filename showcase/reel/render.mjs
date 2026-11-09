import { chromium } from 'playwright';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdir, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const frames = path.join(root, 'tmp', 'frames');
const output = path.join(root, 'output', 'iron-and-snow-reel-silent.mp4');
const python = path.resolve(root, '..', '..', '.venv', 'Scripts', 'python.exe');
const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const fps = 30;

await rm(frames, { recursive: true, force: true });
await mkdir(frames, { recursive: true });
await mkdir(path.dirname(output), { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: chrome });
try {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => console.error('Page error:', e.message));
  console.log('Opening local reel HTML');
  await page.goto(pathToFileURL(path.join(root, 'reel.html')).href, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500);
  console.log('Checking scene assets');
  const loaded = await page.evaluate(() => [...document.images].map(img => ({ src: img.getAttribute('src'), ok: img.complete && img.naturalWidth > 0 })));
  const missing = loaded.filter(x => !x.ok);
  if (missing.length) throw new Error(`Could not load assets: ${missing.map(x => x.src).join(', ')}`);
  const seconds = await page.evaluate(() => window.REEL_DURATION);
  const total = Math.ceil(seconds * fps);
  for (let i = 0; i < total; i++) {
    await page.evaluate(t => window.seekReel(t), i / fps);
    await page.screenshot({ path: path.join(frames, `${String(i).padStart(6, '0')}.jpg`), type: 'jpeg', quality: 88 });
    if (i % 150 === 0) console.log(`Rendered ${i}/${total} frames`);
  }
  const ffmpeg = execFileSync(python, ['-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'], { encoding: 'utf8' }).trim();
  const args = ['-y', '-hide_banner', '-loglevel', 'warning', '-framerate', String(fps), '-i', path.join(frames, '%06d.jpg'), '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output];
  const result = spawnSync(ffmpeg, args, { stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`ffmpeg exited with ${result.status}`);
  console.log(JSON.stringify({ output, seconds, frames: total, fps, width: 1080, height: 1350, bytes: (await stat(output)).size }, null, 2));
} finally {
  await browser.close();
}
