export interface ContingenciaPayload {
  modeloFacturacion: number;
  tipoTransmision: number;
  tipoContingencia: number;
  motivoContingencia?: string;
}

export async function guardarEnContingencia(
  facturaId: string,
  payload: ContingenciaPayload
) {
  const res = await fetch(`/api/facturas/${facturaId}/contingencia`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    throw new Error('Error al guardar en contingencia');
  }
  return await res.json();
}
