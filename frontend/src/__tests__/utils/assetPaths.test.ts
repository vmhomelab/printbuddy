import { beforeEach, describe, expect, it } from 'vitest';
import { appAssetPath, appBasePath } from '../../utils/assetPaths';

describe('assetPaths', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('keeps root-relative assets unchanged outside Home Assistant ingress', () => {
    expect(appBasePath()).toBe('');
    expect(appAssetPath('/img/printbuddy_logo_dark.png')).toBe('/img/printbuddy_logo_dark.png');
  });

  it('prefixes root-relative assets under Home Assistant ingress', () => {
    window.history.replaceState({}, '', '/api/hassio_ingress/abc123/settings');

    expect(appBasePath()).toBe('/api/hassio_ingress/abc123');
    expect(appAssetPath('/img/printbuddy_logo_dark.png')).toBe(
      '/api/hassio_ingress/abc123/img/printbuddy_logo_dark.png'
    );
  });

  it('does not rewrite relative or protocol-relative paths', () => {
    window.history.replaceState({}, '', '/api/hassio_ingress/abc123/');

    expect(appAssetPath('img/printbuddy_logo_dark.png')).toBe('img/printbuddy_logo_dark.png');
    expect(appAssetPath('//cdn.example.test/logo.png')).toBe('//cdn.example.test/logo.png');
  });
});
