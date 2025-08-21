import fs from "fs";
import path from "path";
import axios from "axios";

/**
 * @typedef {Object} IdStore
 * @property {(key: string) => Promise<number>} nextId
 * @property {(key: string, id: number) => Promise<void>} [setLastId]
*/

/**
 * File-backed implementation of IdStore. Stores last idEnvio per key
 * (e.g., per client+ambiente).
 */
export class FileIdStore {
  constructor(filePath = ".dte-state.json") {
    this.filePath = filePath;
    this._queue = Promise.resolve();
  }

  async _read() {
    try {
      const raw = await fs.promises.readFile(this.filePath, "utf8");
      return JSON.parse(raw);
    } catch {
      return { clientes: {} };
    }
  }

  async _write(state) {
    await fs.promises.writeFile(this.filePath, JSON.stringify(state, null, 2));
  }

  /**
   * Get next idEnvio for a key, incrementing stored value.
   * @param {string} key
   * @returns {Promise<number>}
   */
  nextId(key) {
    this._queue = this._queue.then(async () => {
      const state = await this._read();
      const current = state.clientes?.[key]?.idEnvio || 0;
      const next = current + 1;
      state.clientes[key] = { idEnvio: next };
      await this._write(state);
      return next;
    });
    return this._queue;
  }

  /**
   * Ensure stored idEnvio is at least `id` for the key.
   * @param {string} key
   * @param {number} id
   */
  setLastId(key, id) {
    this._queue = this._queue.then(async () => {
      const state = await this._read();
      const current = state.clientes?.[key]?.idEnvio || 0;
      if (id > current) {
        state.clientes[key] = { idEnvio: id };
        await this._write(state);
      }
    });
    return this._queue;
  }
}

function readMaybeFile(input) {
  if (typeof input === "string" && fs.existsSync(input)) {
    const ext = path.extname(input).toLowerCase();
    const raw = fs.readFileSync(input, "utf8");
    if (ext === ".json") return JSON.parse(raw);
    if (ext === ".jws" || ext === ".txt") return raw.trim();
  }
  return input;
}

function isBase64Url(str) {
  return /^[A-Za-z0-9_-]+$/.test(str);
}

/**
 * Validate coherence between DTE and envelope.
 * @param {object} dte
 * @param {object} peticion
 * @param {string} ambiente
 */
export function validatePeticion(dte, peticion, ambiente) {
  const id = dte?.identificacion || {};
  const same = (a, b) => String(a) === String(b);
  if (!same(peticion.version, id.version)) {
    throw new Error("version del sobre no coincide con la del DTE.");
  }
  if (peticion.tipoDte !== id.tipoDte) {
    throw new Error("tipoDte del sobre no coincide con el del DTE.");
  }
  if (peticion.codigoGeneracion !== id.codigoGeneracion) {
    throw new Error("codigoGeneracion del sobre no coincide con el del DTE.");
  }
  if (id.ambiente && ambiente && id.ambiente !== ambiente) {
    throw new Error("ambiente de opciones difiere del DTE.");
  }
}

/**
 * Build envelope (peticion) for DTE reception.
 * @param {*} dteInput
 * @param {*} jwsInput
 * @param {*} options
 * @returns {Promise<object>}
 */
export async function buildPeticion(dteInput, jwsInput, options = {}) {
  const dte = readMaybeFile(dteInput);
  const jws = readMaybeFile(jwsInput);

  if (!dte || !dte.identificacion) {
    throw new Error("DTE inválido: falta nodo 'identificacion'.");
  }
  const parts = typeof jws === "string" ? jws.split(".") : [];
  if (parts.length !== 3 || parts.some((p) => !p || !isBase64Url(p))) {
    throw new Error("JWS inválido: debe ser string compacta con 3 segmentos base64url.");
  }
  if (!options.token || typeof options.token !== "string" || !options.token.trim()) {
    throw new Error("Falta token Bearer.");
  }
  if (!options.clientId || typeof options.clientId !== "string" || !options.clientId.trim()) {
    throw new Error("Falta clientId.");
  }
  if (!options.ambiente || !["00", "01"].includes(options.ambiente)) {
    throw new Error("ambiente debe ser '00' o '01'.");
  }

  const store = options.idStore || new FileIdStore();
  const key = `${options.clientId}:${options.ambiente}`;
  let idEnvio;
  if (options.idEnvio !== undefined) {
    if (!Number.isInteger(options.idEnvio) || options.idEnvio < 1) {
      throw new Error("idEnvio inválido.");
    }
    idEnvio = options.idEnvio;
    if (store.setLastId) await store.setLastId(key, idEnvio);
  } else {
    idEnvio = await store.nextId(key);
  }

  const { version, tipoDte, codigoGeneracion } = dte.identificacion;
  const peticion = {
    ambiente: options.ambiente,
    idEnvio,
    version,
    tipoDte,
    codigoGeneracion,
    documento: jws
  };

  validatePeticion(dte, peticion, options.ambiente);
  return peticion;
}

/**
 * Send envelope to Hacienda API.
 * @param {object} peticion
 * @param {object} options
 * @returns {Promise<object>}
 */
export async function sendRecepcionDTE(peticion, options = {}) {
  const ambiente = options.ambiente;
  const baseUrl =
    options.baseUrl ||
    (ambiente === "01" ? "https://api.dtes.mh.gob.sv" : "https://apitest.dtes.mh.gob.sv");
  const url = `${baseUrl.replace(/\/+$/, "")}/fesv/recepciondte`;
  const raw = (options.token || "").trim();
  const token = raw.startsWith("Bearer ") ? raw.slice(7).trim() : raw;
  const timeout = options.timeoutMs ?? (ambiente === "01" ? 45000 : 30000);
  const ua = options.userAgent || `Vertex-DTE/1.0 (${options.clientId}; env=${ambiente})`;
  const headers = {
    Authorization: `Bearer ${token}`,
    "User-Agent": ua,
    "Content-Type": "application/json"
  };

  const delays = [500, 1500];
  const transient = [429, 502, 503, 504];
  let attempt = 0;
  for (;;) {
    try {
      const resp = await axios.post(url, peticion, { headers, timeout });
      const data = resp.data || {};
      const resumen = {
        statusHttp: resp.status,
        estado: data.estado,
        codigoGeneracion: data.codigoGeneracion,
        selloRecibido: data.selloRecibido,
        fhProcesamiento: data.fhProcesamiento,
        observaciones: data.observaciones
      };
      const brief = Array.isArray(resumen.observaciones)
        ? resumen.observaciones.slice(0, 5)
        : resumen.observaciones;
      console.info("Recepción DTE ->", { ...resumen, observaciones: brief });
      return resumen;
    } catch (err) {
      const status = err.response?.status;
      if (transient.includes(status) && attempt < delays.length) {
        const wait = delays[attempt++];
        await new Promise((r) => setTimeout(r, wait));
        continue;
      }
      if (err.response) {
        const data = err.response.data || {};
        const message = data.mensaje ? ` - ${data.mensaje}` : "";
        const e = new Error(`Error recepción DTE: ${status}${message}`);
        e.statusHttp = status;
        if (data.observaciones) e.observaciones = data.observaciones;
        throw e;
      }
      throw err;
    }
  }
}

// CLI usage
if (process.argv[1] && path.basename(process.argv[1]) === path.basename(new URL(import.meta.url).pathname)) {
  (async () => {
    const [, , dtePath, jwsPath, clientId, ambiente, token] = process.argv;
    const idStore = new FileIdStore();
    const opts = { clientId, ambiente, token, idStore };
    const peticion = await buildPeticion(dtePath, jwsPath, opts);
    const resumen = await sendRecepcionDTE(peticion, opts);
    console.log(resumen);
  })();
}

