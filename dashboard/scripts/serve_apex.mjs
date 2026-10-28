#!/usr/bin/env node
///////////////////////////////////////////////////////////////////////////////
// Local preview for the apex portfolio (dram-soc.org).
//
// Serves dashboard/frontend-apex/ as the site root, the way the host-router
// CloudFront Function maps dram-soc.org/* onto apex/* in production, and
// sends the same security headers as the response headers policy in
// infrastructure/terraform/modules/hosting/main.tf. Anything the production
// CSP would block (inline <script>, <object>, a new third-party origin) is
// blocked here too. Open tabs reload when a file in the folder changes.
//
// Usage (from repo root or anywhere):
//   node dashboard/scripts/serve_apex.mjs [port]     # default 4322
//
// Deploy with dashboard/scripts/deploy_apex.sh.
///////////////////////////////////////////////////////////////////////////////

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { watch } from "node:fs";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("../frontend-apex/", import.meta.url)));
const PORT = Number(process.argv[2] || process.env.PORT || 4322);

// Keep in step with aws_cloudfront_response_headers_policy.frontend. HSTS is
// left out on purpose: it means nothing over plain-http localhost.
const SECURITY_HEADERS = {
  "Content-Security-Policy": [
    "default-src 'self';",
    "script-src 'self';",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;",
    "img-src 'self' data:;",
    "connect-src 'self' https://mlncxsr5a9.execute-api.us-east-1.amazonaws.com;",
    "font-src 'self' data: https://fonts.gstatic.com;",
    "object-src 'none';",
    "base-uri 'self';",
    "frame-ancestors 'none'",
  ].join(" "),
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
};

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".webm": "video/webm",
  ".mp4": "video/mp4",
  ".pdf": "application/pdf",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

// Live reload over Server-Sent Events. The client is an external script so
// it passes script-src 'self'; EventSource passes connect-src 'self'.
const RELOAD_JS = 'new EventSource("/__reload").onmessage = () => location.reload();\n';
const clients = new Set();

let pending;
watch(ROOT, { recursive: true }, (_event, file) => {
  clearTimeout(pending);
  pending = setTimeout(() => {
    console.log(`changed: ${file} -> reloading ${clients.size} tab(s)`);
    for (const res of clients) res.write("data: reload\n\n");
  }, 100);
});

const send = (res, status, type, body) => {
  res.writeHead(status, { ...SECURITY_HEADERS, "Content-Type": type, "Cache-Control": "no-store" });
  res.end(body);
};

createServer(async (req, res) => {
  const { pathname } = new URL(req.url, "http://localhost");

  if (pathname === "/__reload") {
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-store" });
    res.write(": connected\n\n");
    clients.add(res);
    req.on("close", () => clients.delete(res));
    return;
  }
  if (pathname === "/__reload.js") return send(res, 200, TYPES[".js"], RELOAD_JS);

  // Same rewrite as the host-router function: dir-style paths get index.html.
  let uri = decodeURIComponent(pathname);
  if (uri.endsWith("/")) uri += "index.html";
  const file = resolve(join(ROOT, uri));
  if (file !== ROOT && !file.startsWith(ROOT + sep)) return send(res, 403, TYPES[".txt"], "forbidden\n");

  try {
    if (!(await stat(file)).isFile()) throw new Error("not a file");
    const type = TYPES[extname(file).toLowerCase()] || "application/octet-stream";
    let body = await readFile(file);
    if (type.startsWith("text/html")) {
      const html = body.toString("utf8");
      const tag = '<script src="/__reload.js"></script>';
      const at = html.toLowerCase().lastIndexOf("</body>");
      body = at === -1 ? html + tag : html.slice(0, at) + tag + html.slice(at);
    }
    send(res, 200, type, body);
  } catch {
    // Production would answer a missing file with the dashboard SPA's
    // index.html (its 404 fallback), which hides broken links. Fail loudly.
    console.log(`404: ${pathname}`);
    send(res, 404, TYPES[".txt"], `404: ${pathname} is not in frontend-apex/\n`);
  }
})
  .on("error", (err) => {
    console.error(err.code === "EADDRINUSE" ? `port ${PORT} is in use; pass another: node serve_apex.mjs 4323` : err);
    process.exit(1);
  })
  .listen(PORT, "127.0.0.1", () => {
    console.log(`apex preview: http://localhost:${PORT}/  (serving ${ROOT})`);
  });
