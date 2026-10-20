// shop: a small HTTP service on Postgres.
//   GET /order?customer=C&amount=A[&email=E]  -> insert an order (guest orders have no email)
//   GET /order/ID                             -> read one order
//   GET /customer/C                           -> a customer's last 10 orders (slow without an index)
// Which columns the app uses is set by environment variables:
//   AMOUNT_READ   column the amount is read from            (default: amount)
//   AMOUNT_WRITE  column(s) the amount is written to, comma (default: amount)
//   GUEST_EMAIL   what a guest order stores as email: null | empty   (default: null)
// Every query has a 2 s statement timeout.
const http = require("http");
const { Pool } = require("pg");

const AMOUNT_READ = process.env.AMOUNT_READ || "amount";
const AMOUNT_WRITE = (process.env.AMOUNT_WRITE || "amount").split(",").map((s) => s.trim()).filter(Boolean);
const GUEST_EMAIL = process.env.GUEST_EMAIL === "empty" ? "" : null;
const ident = (s) => { if (!/^[a-z_][a-z0-9_]*$/.test(s)) throw new Error("bad column name " + s); return s; };

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 8,
  connectionTimeoutMillis: 2000,
  options: "-c statement_timeout=2000",
});

const insertSql = `INSERT INTO orders (customer_id, ${AMOUNT_WRITE.map(ident).join(", ")}, status, email)
                   VALUES ($1, ${AMOUNT_WRITE.map(() => "$2").join(", ")}, 'new', $3) RETURNING id`;
const readSql = `SELECT id, customer_id, ${ident(AMOUNT_READ)} AS amount, status, email FROM orders WHERE id = $1`;
const customerSql = `SELECT id, ${ident(AMOUNT_READ)} AS amount FROM orders WHERE customer_id = $1 ORDER BY id DESC LIMIT 10`;

let stopping = false;
function send(res, code, body) {
  res.writeHead(code, { "content-type": "application/json", ...(stopping ? { connection: "close" } : {}) });
  res.end(JSON.stringify(body));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  try {
    if (url.pathname === "/healthz") return send(res, stopping ? 503 : 200, { ok: !stopping });   // not ready once stopping
    if (url.pathname === "/order") {
      const email = url.searchParams.get("email") || GUEST_EMAIL;
      const r = await pool.query(insertSql, [Number(url.searchParams.get("customer")), url.searchParams.get("amount"), email]);
      return send(res, 200, { id: r.rows[0].id });
    }
    let m = url.pathname.match(/^\/order\/(\d+)$/);
    if (m) {
      const r = await pool.query(readSql, [m[1]]);
      return r.rows.length ? send(res, 200, r.rows[0]) : send(res, 404, { error: "not found" });
    }
    m = url.pathname.match(/^\/customer\/(\d+)$/);
    if (m) {
      const r = await pool.query(customerSql, [m[1]]);
      return send(res, 200, { orders: r.rows });
    }
    send(res, 404, { error: "no route" });
  } catch (e) {
    send(res, 500, { error: String(e.message || e).slice(0, 200) });
  }
});
server.listen(8080, () => console.log(`shop on 8080: read ${AMOUNT_READ}, write ${AMOUNT_WRITE}, guest email ${GUEST_EMAIL === null ? "NULL" : "''"}`));

// Graceful shutdown. Node runs as PID 1 in the container, where SIGTERM does nothing unless handled: an old pod
// would keep serving the OLD app version on open keep-alive connections for the whole 30 s grace period.
// So: stop keeping connections alive, give the Service 3 s to stop routing here, finish in-flight requests, exit.
process.on("SIGTERM", () => {
  stopping = true;
  setTimeout(() => {
    server.close(() => pool.end().finally(() => process.exit(0)));
    server.closeIdleConnections();
  }, 3000);
});
