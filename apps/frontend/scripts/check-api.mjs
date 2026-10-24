// M0-AC06 (TS side): regenerate types from the approved OpenAPI snapshot into a temp file
// and fail if they differ from the committed src/lib/api/schema.d.ts.
// Optional env CHECK_API_SCHEMA overrides the committed file path (used by the drift test).
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const committed = process.env.CHECK_API_SCHEMA ?? join(root, 'src/lib/api/schema.d.ts');
const spec = process.env.CHECK_API_SPEC ?? resolve(root, '../../docs/contracts/openapi.json');
const dir = mkdtempSync(join(tmpdir(), 'ks-api-'));
const out = join(dir, 'schema.d.ts');
try {
  const bin = join(root, 'node_modules/openapi-typescript/bin/cli.js');
  const r = spawnSync(process.execPath, [bin, spec, '-o', out], { stdio: 'inherit' });
  if (r.status !== 0) {
    console.error('check:api: openapi-typescript failed');
    process.exit(1);
  }
  const norm = (p) => readFileSync(p, 'utf8').replace(/\r\n/g, '\n');
  if (norm(out) !== norm(committed)) {
    console.error(
      'check:api: committed schema.d.ts differs from the OpenAPI contract. Run `pnpm gen:api`.',
    );
    process.exit(1);
  }
  console.log('check:api: schema.d.ts matches docs/contracts/openapi.json');
} finally {
  rmSync(dir, { recursive: true, force: true });
}
