export function sanitizeDocs<T>(data: T): T {
  function walk(obj: any) {
    if (!obj || typeof obj !== 'object') return;
    for (const key of Object.keys(obj)) {
      const val = obj[key];
      if (val && typeof val === 'object') {
        walk(val);
      } else if (typeof val === 'string') {
        const kl = key.toLowerCase();
        if (kl === 'nit' || kl === 'dui' || kl === 'numdocumento' || kl.includes('documento')) {
          obj[key] = val.replace(/[-\s]/g, '');
        }
      }
    }
  }
  if (data && typeof data === 'object') {
    const clone: any = Array.isArray(data) ? [...(data as any)] : { ...(data as any) };
    walk(clone);
    return clone;
  }
  return data;
}
