export async function previsualizarPdf(notaId: string) {
  const res = await fetch(`/api/notas/${notaId}/pdf`);
  if (!res.ok) {
    throw new Error('Error al previsualizar PDF');
  }
  return await res.blob();
}

export async function previsualizarJson(notaId: string) {
  const res = await fetch(`/api/notas/${notaId}/json`);
  if (!res.ok) {
    throw new Error('Error al previsualizar JSON');
  }
  return await res.json();
}

export async function guardarBorrador(nota: any) {
  const res = await fetch('/api/notas/borrador', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(nota),
  });
  if (!res.ok) {
    throw new Error('Error al guardar borrador');
  }
  return await res.json();
}

export async function firmarTransmitir(nota: any) {
  const res = await fetch('/api/notas/firmar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(nota),
  });
  if (!res.ok) {
    throw new Error('Error al firmar y transmitir');
  }
  return await res.json();
}
