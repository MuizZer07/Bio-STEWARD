// Bundles the extension into dist/extension.js (CommonJS, Node, `vscode` left external).
// `node esbuild.mjs --production` minifies and drops source maps, for `vsce package`.
import { build } from 'esbuild';

const production = process.argv.includes('--production');

await build({
  entryPoints: ['src/extension.ts'],
  outfile: 'dist/extension.js',
  bundle: true,
  format: 'cjs',
  platform: 'node',
  target: 'node20',
  external: ['vscode'],
  minify: production,
  sourcemap: !production,
  sourcesContent: false,
  legalComments: 'linked',
  logLevel: 'info',
});
