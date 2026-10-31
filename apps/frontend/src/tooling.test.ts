import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = resolve(import.meta.dirname, '..');

describe('m0_ac06 / fe_arch_08 tooling gates', () => {
  it('m0_ac06_check_api_passes_on_committed_schema', () => {
    const r = spawnSync(process.execPath, ['scripts/check-api.mjs'], {
      cwd: root,
      encoding: 'utf8',
    });
    expect(r.status).toBe(0);
  });

  it('m0_ac06_check_api_fails_when_schema_drifts', () => {
    const dir = mkdtempSync(join(tmpdir(), 'ks-drift-'));
    try {
      const drifted = join(dir, 'schema.d.ts');
      writeFileSync(
        drifted,
        readFileSync(join(root, 'src/lib/api/schema.d.ts'), 'utf8') + '\n// drift\n',
      );
      const r = spawnSync(process.execPath, ['scripts/check-api.mjs'], {
        cwd: root,
        encoding: 'utf8',
        env: { ...process.env, CHECK_API_SCHEMA: drifted },
      });
      expect(r.status).toBe(1);
      expect(r.stderr).toContain('differs');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('fe_arch_08_lint_fails_on_jsx_style_attribute', () => {
    const file = join(root, 'src/__lint_probe__.tsx');
    writeFileSync(file, 'export const X = () => <div style={{ color: "red" }} />;\n');
    try {
      const eslint = join(root, 'node_modules/eslint/bin/eslint.js');
      const r = spawnSync(process.execPath, [eslint, file], { cwd: root, encoding: 'utf8' });
      expect(r.status).toBe(1);
      expect(r.stdout).toContain('no-restricted-syntax');
    } finally {
      rmSync(file, { force: true });
    }
  });
});
