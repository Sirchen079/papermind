import { copyFileSync, createReadStream, existsSync, mkdirSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy must point at the backend. Default 4278 to match start.ps1/dev.ps1;
// override with PAPERMIND_PORT if you run the backend on a different port.
const backendPort = process.env.PAPERMIND_PORT || "4278";

// P11 内置阅读器：pdfjs 渲染中文 PDF 依赖 cMaps 与标准字体数据。这些文件随
// pdfjs-dist 包发布（上百个小文件），不拷贝进仓库：
// - dev：中间件把 /pdfjs/{cmaps,standard_fonts}/* 直接从 node_modules 读出；
// - build：closeBundle 把两份资源拷进 dist/pdfjs/（后端 StaticFiles 服务 dist）。
// 两条路径一致，阅读器只需配置 cMapUrl="/pdfjs/cmaps/" 等。
const PDFJS_PREFIXES: Record<string, string> = {
  "/pdfjs/cmaps/": "cmaps",
  "/pdfjs/standard_fonts/": "standard_fonts",
};

function pdfjsAssets(): Plugin {
  const pkgDir = fileURLToPath(new URL("./node_modules/pdfjs-dist", import.meta.url));
  let distDir = "";

  return {
    name: "papermind-pdfjs-assets",
    configResolved(config) {
      distDir = resolve(config.root, config.build.outDir);
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? "";
        for (const [prefix, sub] of Object.entries(PDFJS_PREFIXES)) {
          if (!url.startsWith(prefix)) continue;
          const rel = decodeURIComponent(url.slice(prefix.length).split("?")[0]);
          const root = resolve(pkgDir, sub);
          const file = resolve(root, rel);
          if (!file.startsWith(root) || !existsSync(file) || !statSync(file).isFile()) {
            next();
            return;
          }
          res.setHeader("Content-Type", "application/octet-stream");
          createReadStream(file).pipe(res);
          return;
        }
        next();
      });
    },
    closeBundle() {
      if (!distDir) return;
      for (const sub of Object.values(PDFJS_PREFIXES)) {
        const src = resolve(pkgDir, sub);
        const dest = resolve(distDir, "pdfjs", sub);
        mkdirSync(dest, { recursive: true });
        for (const name of readdirSync(src)) {
          const file = resolve(src, name);
          if (statSync(file).isFile()) copyFileSync(file, resolve(dest, name));
        }
      }
    },
  };
}

// Dev 模式页面由 Vite 提供，而生产模式后端会在 index.html 注入
// <meta name="papermind-local-token" content="...">。为让 dev 页面也能读到
// token（请求需带 X-Local-Token，否则 403），dev server 转换 index.html 时
// 惰性读取 backend/data/api_token（目录可用 PAPERMIND_DATA_DIR 覆盖）并注入。
// 纯函数：对 token 做 HTML 属性转义，插到第一个 </head> 前；
// token 为空或 html 无 </head> 时原样返回。
function escapeHtmlAttr(value: string): string {
  return value.replace(/[&"<>/]/g, (ch) => {
    switch (ch) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#47;"; // "/"
    }
  });
}

export function injectTokenMeta(html: string, token: string): string {
  if (!token) return html;
  const headEnd = html.indexOf("</head>");
  if (headEnd === -1) return html;
  const meta = `<meta name="papermind-local-token" content="${escapeHtmlAttr(token)}">`;
  return html.slice(0, headEnd) + meta + html.slice(headEnd);
}

function localTokenMeta(): Plugin {
  // vite config 以 ESM 加载，无 __dirname；此行等价于 path.resolve(__dirname, "../backend/data")。
  const defaultDataDir = fileURLToPath(new URL("../backend/data", import.meta.url));
  let warnedOnce = false;

  return {
    name: "papermind-local-token",
    // 仅 dev server 生效：build 产物的 meta 由后端在运行时注入，
    // 避免把当时的 token 固化进 dist（token 轮换后会失效/重复）。
    apply: "serve",
    transformIndexHtml(html) {
      let token = "";
      try {
        const dataDir = process.env.PAPERMIND_DATA_DIR || defaultDataDir;
        token = readFileSync(resolve(dataDir, "api_token"), "utf8").trim();
      } catch {
        token = "";
      }
      if (!token) {
        if (!warnedOnce) {
          warnedOnce = true;
          console.warn(
            "[papermind-local-token] backend api_token not found; token-protected actions will 403 until backend runs",
          );
        }
        return html;
      }
      return injectTokenMeta(html, token);
    },
  };
}

export default defineConfig({
  plugins: [react(), pdfjsAssets(), localTokenMeta()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${backendPort}`,
        // 把 Host 头改写为 target 的主机名（127.0.0.1），配合后端
        // TrustedHostMiddleware 白名单（localhost/127.0.0.1/testserver）。
        changeOrigin: true,
      },
    },
  },
});
