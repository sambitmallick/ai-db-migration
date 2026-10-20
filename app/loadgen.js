// loadgen: live traffic for the whole migration. RATE requests/s for SECONDS, from inside the cluster.
// Mix: half place an order, half read one. (The customer page is left out: until it has an index it is a 10M-row
// scan whose speed depends on whatever else the disk is doing, which would blur what the migration itself did.)
// One JSON line per request:
//   {at (epoch ms), kind, status, ms, id?, amount?, email?, err?}  (status 0 = no response within 3 s)
// The orders it placed (id, amount, email) are how the harness later checks that no write was lost.
const http = require("http");
const RATE = Number(process.env.RATE || 60), SECONDS = Number(process.env.SECONDS || 150);
const BASE = process.env.TARGET || "http://shop:8080";
const MAX_ID = Number(process.env.MAX_ID || 10000000), CUSTOMERS = Number(process.env.CUSTOMERS || 50000);
const agent = new http.Agent({ keepAlive: true, maxSockets: 200 });

function get(path) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const req = http.get(BASE + path, { agent, timeout: 3000 }, (res) => {
      let body = "";
      res.on("data", (c) => (body += c));
      res.on("end", () => resolve({ status: res.statusCode, ms: Date.now() - t0, body }));
    });
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", () => resolve({ status: 0, ms: Date.now() - t0, body: "" }));
  });
}

const err = (res) => (res.status === 200 || res.status === 404 ? {} : { err: res.body.slice(0, 160) || "no response" });

async function one() {
  const at = Date.now(), r = Math.random();
  if (r < 0.5) {
    const amount = (1 + Math.floor(Math.random() * 99999) / 100).toFixed(2);
    const email = Math.random() < 0.25 ? null : `c${Math.floor(Math.random() * 1e6)}@shop.test`;
    const customer = 1 + Math.floor(Math.random() * CUSTOMERS);
    const res = await get(`/order?customer=${customer}&amount=${amount}` + (email ? `&email=${email}` : ""));
    let id = null; try { id = JSON.parse(res.body).id; } catch {}
    console.log(JSON.stringify({ at, kind: "write", status: res.status, ms: res.ms, id, amount, email, customer, ...err(res) }));
  } else {
    const res = await get(`/order/${1 + Math.floor(Math.random() * MAX_ID)}`);
    console.log(JSON.stringify({ at, kind: "read", status: res.status, ms: res.ms, ...err(res) }));
  }
}

const start = Date.now(), pending = [];
console.error(`loadgen: ${RATE}/s for ${SECONDS}s against ${BASE}, start ${start}`);
const timer = setInterval(() => {
  if (Date.now() - start >= SECONDS * 1000) { clearInterval(timer); Promise.all(pending).then(() => console.error("done")); return; }
  pending.push(one());
}, 1000 / RATE);
