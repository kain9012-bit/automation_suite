import fs from "node:fs/promises";
import path from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const host = process.env.TAURI_DEV_HOST;
const projectRoot = process.cwd();
const toolsRoot = path.join(projectRoot, "tools");

async function readToolRegistry() {
  const entries = await fs.readdir(toolsRoot, { withFileTypes: true });
  const tools = [];

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const manifestPath = path.join(toolsRoot, entry.name, "manifest.json");
    try {
      const raw = await fs.readFile(manifestPath, "utf8");
      const manifest = JSON.parse(raw);
      const htmlEntry = path.join(toolsRoot, entry.name, manifest.entry ?? "");
      const fallbackHtml = path.join(toolsRoot, entry.name, "web", "index.html");
      let hasHtml = false;
      if (manifest.type === "html") {
        hasHtml = await fs.stat(htmlEntry).then(() => true).catch(() => false);
      } else {
        hasHtml = await fs.stat(fallbackHtml).then(() => true).catch(() => false);
      }
      tools.push({ ...manifest, source: "builtin", has_html: hasHtml });
    } catch {
      // A malformed tool must not prevent the rest of the suite from loading.
    }
  }

  return tools.sort((a, b) =>
    String(a.name ?? a.id).localeCompare(String(b.name ?? b.id), "ko"),
  );
}

function toolDevApi(): Plugin {
  return {
    name: "automation-suite-tool-dev-api",
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const requestUrl = new URL(req.url ?? "/", "http://localhost");

        if (requestUrl.pathname === "/dev-tools.json") {
          try {
            const tools = await readToolRegistry();
            res.statusCode = 200;
            res.setHeader("Content-Type", "application/json; charset=utf-8");
            res.end(JSON.stringify(tools));
          } catch (error) {
            res.statusCode = 500;
            res.end(String(error));
          }
          return;
        }

        if (requestUrl.pathname.startsWith("/dev-html/")) {
          const toolId = decodeURIComponent(requestUrl.pathname.slice("/dev-html/".length));
          if (!/^[a-zA-Z0-9_-]+$/.test(toolId)) {
            res.statusCode = 400;
            res.end("Invalid tool id");
            return;
          }

          try {
            const manifestPath = path.join(toolsRoot, toolId, "manifest.json");
            const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
            const relativeEntry =
              manifest.type === "html" ? manifest.entry : path.join("web", "index.html");
            const htmlPath = path.resolve(toolsRoot, toolId, relativeEntry);
            const toolRoot = path.resolve(toolsRoot, toolId);
            if (!htmlPath.startsWith(`${toolRoot}${path.sep}`)) {
              throw new Error("HTML entry leaves the tool directory");
            }
            const html = await fs.readFile(htmlPath, "utf8");
            res.statusCode = 200;
            res.setHeader("Content-Type", "text/html; charset=utf-8");
            res.end(html);
          } catch {
            res.statusCode = 404;
            res.end("HTML tool not found");
          }
          return;
        }

        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), toolDevApi()],
  clearScreen: false,
  server: {
    port: 5174,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 5175 } : undefined,
    watch: {
      ignored: ["**/src-tauri/**", "**/build/**", "**/dist/**"],
    },
  },
});
