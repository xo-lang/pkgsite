// node width.mjs BASE LIST PROFILE: each path of LIST (one per line) at 390x844,
// mobile, in one headless Chrome (CHROME names its binary); prints JSON lines
// {path, scrollWidth, innerWidth, wide}: scrollWidth over innerWidth is a
// horizontal scroll. PROFILE is an empty scratch directory for Chrome.
import { spawn } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
const [base, list, prof] = process.argv.slice(2);
const paths = readFileSync(list, "utf8").split("\n").filter(Boolean);
const chrome = spawn(process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new", "--disable-gpu", "--remote-debugging-port=0", `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
const portFile = `${prof}/DevToolsActivePort`;
for (let i = 0; i < 100 && !existsSync(portFile); i++) await new Promise(r => setTimeout(r, 100));
const port = readFileSync(portFile, "utf8").split("\n")[0];
const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const waits = new Map(); let loaded = null;
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (waits.has(d.id)) { waits.get(d.id)(d); waits.delete(d.id); } if (d.method === "Page.loadEventFired" && loaded) { loaded(); loaded = null; } };
const send = (method, params = {}) => new Promise(r => { const i = ++id; waits.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await send("Page.enable");
const ev = async (e) => (await send("Runtime.evaluate", { expression: e, returnByValue: true })).result.result.value;
for (const p of paths) {
  const done = new Promise(r => { loaded = r; setTimeout(r, 10000); });
  await send("Page.navigate", { url: base + p });
  await done;
  const sw = await ev("document.documentElement.scrollWidth"), iw = await ev("innerWidth");
  const wide = sw > iw ? await ev(`[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.right>innerWidth+1&&!e.closest('pre')}).slice(0,4).map(e=>e.tagName+(e.id?'#'+e.id:'')+' '+Math.round(e.getBoundingClientRect().right))`) : [];
  console.log(JSON.stringify({ path: p, scrollWidth: sw, innerWidth: iw, wide }));
}
ws.close(); chrome.kill();
