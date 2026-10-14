import assert from 'node:assert/strict';
import test from 'node:test';
import { withRegistryLogo } from '../frontend/src/assets/appIconIdentity.js';

test('mounted app identity supplies the same public asset used by the shell', () => {
  const app = { app_id: 'example-app' };
  const logo = { kind: 'image', value: '/apps/example-app/loopino-icon-compact.png' };
  assert.deepEqual(withRegistryLogo(app, [{ app_id: 'example-app', logo }]), { ...app, logo });
  assert.equal(app.logo, undefined);
});

test('public identity prevents fork collisions and preserves explicit catalog logos', () => {
  const app = { app_id: 'notes' };
  const registry = [{ app_id: 'notes', public_app_id: 'private-fork', logo: { kind: 'image', value: '/apps/private-fork/icon.png' } }];
  assert.equal(withRegistryLogo(app, registry), app);
  assert.equal(withRegistryLogo(app, []), app);
  const explicit = { ...app, logo: { kind: 'glyph', value: 'description' } };
  assert.equal(withRegistryLogo(explicit, registry), explicit);
  assert.equal(withRegistryLogo({ app_id: 'private-fork' }, registry).logo, registry[0].logo);
});
