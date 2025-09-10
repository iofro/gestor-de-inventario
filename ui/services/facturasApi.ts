export async function guardarEnContingencia(
  facturaId: string,
  tipoContingencia: number,
  motivoContin = ''
) {
  const res = await fetch(`/api/facturas/${facturaId}/contingencia`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tipoContingencia, motivoContin })
  });
  if (!res.ok) {
    throw new Error('Error al guardar en contingencia');
  }
  return await res.json();
}
