import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';

// Exercise the page's host callbacks without WebGL, using its actual method bodies.
const page = readFileSync(new URL('./avatar.js', import.meta.url), 'utf8');
function callbacks() {
  const context = createContext({
    window: { innerWidth: 300, innerHeight: 520 }, canvas: { style: {} },
    hide: { id: 7 }, walk: null, jumping: null, perched: { low: true }, visit: null,
    stageX: 0, stageY: 0, pxPerUnit: 400, t: 1,
  });
  const end = page.match(/^function endHide\(\) \{[\s\S]*?^\}/m)[0];
  const methods = ['setCover', 'stopTrip', 'unhide'].map(name =>
    page.match(new RegExp(`^  ${name}\\([^\\n]*\\) \\{[\\s\\S]*?^  \\},`, 'm'))[0]);
  runInContext(`${end}\nwindow.aria = {${methods.join('\n')}};`, context);
  return context;
}
const cover = { left: 0, top: 260, right: 300, bottom: 520 };

test('ending a hide clears the lower-body cut and rejects a late cover', () => {
  for (const method of ['stopTrip', 'unhide']) {
    const c = callbacks();
    c.window.aria.setCover(cover);
    assert.match(c.canvas.style.clipPath, /evenodd/);
    c.window.aria[method]();
    assert.equal(c.canvas.style.clipPath, '');
    assert.equal(c.window.ariaBehind, null);
    c.window.aria.setCover(cover);
    assert.equal(c.canvas.style.clipPath, '');
    if (method === 'stopTrip') assert.equal(c.perched, null);
  }
});

test('the host can clear a cover while hiding, and malformed covers cannot hide her', () => {
  const c = callbacks();
  for (const invalid of [null, { ...cover, bottom: NaN }]) {
    c.window.aria.setCover(cover);
    assert.ok(c.canvas.style.clipPath);
    c.window.aria.setCover(invalid);
    assert.equal(c.canvas.style.clipPath, '');
  }
});

test('a screen change can cancel a panel jump and discard its lower-body cover', () => {
  const c = callbacks();
  c.window.aria.setCover(cover);
  c.jumping = { id: 12, base: 0 };
  c.stageY = -0.5;
  c.window.aria.stopTrip();
  assert.equal(c.jumping, null);
  assert.equal(c.perched, null);
  assert.equal(c.canvas.style.clipPath, '');
  assert.deepEqual(Array.from(c.window.ariaTravel), [12, 0, false, 200]);
  c.window.aria.setCover(cover);
  assert.equal(c.canvas.style.clipPath, '', 'a delayed cover cannot crop her after relocation');
});
