export function appBasePath(): string {
  if (typeof window === 'undefined') return '';
  const match = window.location.pathname.match(/^(.*\/api\/hassio_ingress\/[^/]+)(?:\/|$)/);
  return match?.[1] ?? '';
}

export function appAssetPath(path: string): string {
  if (!path.startsWith('/') || path.startsWith('//')) return path;
  const base = appBasePath();
  return base ? `${base}${path}` : path;
}
