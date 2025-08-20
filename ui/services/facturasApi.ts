export async function guardarEnContingencia(facturaId: string) {
  const res = await fetch(`/api/facturas/${facturaId}/contingencia`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error('Error al guardar en contingencia');
  }
  return await res.json();
}
