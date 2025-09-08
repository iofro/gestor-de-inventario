import { sanitizeDocs } from './sanitize';

export async function previsualizarPdf(data: any) {
  const res = await fetch('/api/notas/previsualizar/pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sanitizeDocs(data)),
  });
  if (!res.ok) throw new Error('Error al previsualizar PDF');
  return await res.blob();
}

export async function previsualizarJson(data: any) {
  const res = await fetch('/api/notas/previsualizar/json', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sanitizeDocs(data)),
  });
  if (!res.ok) throw new Error('Error al previsualizar JSON');
  return await res.json();
}

export async function guardarBorrador(data: any) {
  const res = await fetch('/api/notas/borrador', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sanitizeDocs(data)),
  });
  if (!res.ok) throw new Error('Error al guardar borrador');
  return await res.json();
}

export async function firmarTransmitir(data: any) {
  const res = await fetch('/api/notas/firmar-transmitir', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sanitizeDocs(data)),
  });
  if (!res.ok) throw new Error('Error al firmar y transmitir');
  return await res.json();
}
