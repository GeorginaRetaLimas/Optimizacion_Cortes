// Compila la interfaz a frontend/dist (la sirve el backend Flask).
// Uso: npm run build   |   npm run dev (recompila al guardar)
import * as esbuild from "esbuild";
import { cpSync, mkdirSync } from "node:fs";
import path from "node:path";

const watch = process.argv.includes("--watch");
mkdirSync("dist", { recursive: true });
cpSync("public", "dist", { recursive: true });

const options = {
  entryPoints: ["src/main.jsx"],
  bundle: true,
  outfile: "dist/app.js",
  minify: !watch,
  sourcemap: watch,
  jsx: "automatic",
  target: ["es2020"],
  loader: { ".jsx": "jsx" },
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
  nodePaths: (process.env.NODE_PATH || "").split(path.delimiter).filter(Boolean),
  logLevel: "info",
};

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
} else {
  await esbuild.build(options);
}
