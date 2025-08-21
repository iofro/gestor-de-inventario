import { describe, it, expect, vi, beforeEach } from "vitest";
import os from "os";
import path from "path";
import axios from "axios";
import { buildPeticion, sendRecepcionDTE, FileIdStore, validatePeticion } from "./DTE.js";

const sampleDte = {
  identificacion: {
    version: "1.0",
    tipoDte: "01",
    codigoGeneracion: "ABC123",
    ambiente: "00"
  }
};

const validJws = "aaa.bbb.ccc";

describe("buildPeticion validations", () => {
  it("rechaza JWS inválido", async () => {
    await expect(
      buildPeticion(sampleDte, "invalido", { token: "t", clientId: "c", ambiente: "00" })
    ).rejects.toThrow();
    await expect(
      buildPeticion(sampleDte, "a.b.c$", { token: "t", clientId: "c", ambiente: "00" })
    ).rejects.toThrow();
    await expect(
      buildPeticion(sampleDte, "a..c", { token: "t", clientId: "c", ambiente: "00" })
    ).rejects.toThrow();
  });

  it("rechaza token vacío", async () => {
    await expect(
      buildPeticion(sampleDte, validJws, { token: "", clientId: "c", ambiente: "00" })
    ).rejects.toThrow("Falta token");
  });

  it("rechaza ambiente inválido", async () => {
    await expect(
      buildPeticion(sampleDte, validJws, { token: "t", clientId: "c", ambiente: "02" })
    ).rejects.toThrow("ambiente");
  });

  it("falla si sobre y DTE no coinciden", () => {
    const peticion = {
      ambiente: "00",
      idEnvio: 1,
      version: "2.0",
      tipoDte: "01",
      codigoGeneracion: "ABC123",
      documento: validJws
    };
    expect(() => validatePeticion(sampleDte, peticion, "00")).toThrow("version");
  });

  it("falla si ambiente difiere del DTE", async () => {
    const dte = { identificacion: { ...sampleDte.identificacion, ambiente: "01" } };
    await expect(
      buildPeticion(dte, validJws, { token: "t", clientId: "c", ambiente: "00" })
    ).rejects.toThrow("ambiente");
  });

  it("acepta version numérica equivalente", () => {
    const dte = { identificacion: { ...sampleDte.identificacion, version: 1 } };
    const peticion = {
      ambiente: "00",
      idEnvio: 1,
      version: "1",
      tipoDte: dte.identificacion.tipoDte,
      codigoGeneracion: dte.identificacion.codigoGeneracion,
      documento: validJws
    };
    expect(() => validatePeticion(dte, peticion, "00")).not.toThrow();
  });
});

describe("FileIdStore", () => {
  let tmpFile;
  let store;
  beforeEach(() => {
    tmpFile = path.join(os.tmpdir(), `dte-state-${Math.random()}`);
    store = new FileIdStore(tmpFile);
  });

  it("genera ids incrementales por cliente y respeta idEnvio manual", async () => {
    expect(await store.nextId("A:00")).toBe(1);
    expect(await store.nextId("A:00")).toBe(2);
    expect(await store.nextId("A:01")).toBe(1);

    await buildPeticion(sampleDte, validJws, {
      token: "t",
      clientId: "A",
      ambiente: "00",
      idStore: store,
      idEnvio: 5
    });
    expect(await store.nextId("A:00")).toBe(6);
  });
});

describe("sendRecepcionDTE", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("arma URL y headers y retorna resumen", async () => {
    vi.spyOn(axios, "post").mockResolvedValue({
      status: 200,
      data: {
        estado: "RECIBIDO",
        codigoGeneracion: "ABC123",
        selloRecibido: "SELLO",
        fhProcesamiento: "2024-01-01",
        observaciones: ["ok"]
      }
    });
    const peticion = await buildPeticion(sampleDte, validJws, {
      token: "Bearer TKN",
      clientId: "C1",
      ambiente: "00"
    });
    const resumen = await sendRecepcionDTE(peticion, {
      token: "Bearer TKN",
      clientId: "C1",
      ambiente: "00"
    });
    expect(axios.post).toHaveBeenCalledWith(
      "https://apitest.dtes.mh.gob.sv/fesv/recepciondte",
      peticion,
      {
        headers: {
          Authorization: "Bearer TKN",
          "User-Agent": "Vertex-DTE/1.0 (C1; env=00)",
          "Content-Type": "application/json"
        },
        timeout: 30000
      }
    );
    expect(resumen.estado).toBe("RECIBIDO");
  });

  it("usa timeout y User-Agent según ambiente", async () => {
    vi.spyOn(axios, "post").mockResolvedValue({ status: 200, data: {} });
    const dteProd = { identificacion: { ...sampleDte.identificacion, ambiente: "01" } };
    const peticion = await buildPeticion(dteProd, validJws, {
      token: "Bearer TKN",
      clientId: "C1",
      ambiente: "01"
    });
    await sendRecepcionDTE(peticion, { token: "Bearer TKN", clientId: "C1", ambiente: "01" });
    expect(axios.post).toHaveBeenCalledWith(
      "https://api.dtes.mh.gob.sv/fesv/recepciondte",
      peticion,
      {
        headers: {
          Authorization: "Bearer TKN",
          "User-Agent": "Vertex-DTE/1.0 (C1; env=01)",
          "Content-Type": "application/json"
        },
        timeout: 45000
      }
    );
  });

  it("loggea observaciones resumidas", async () => {
    vi.spyOn(axios, "post").mockResolvedValue({
      status: 200,
      data: {
        estado: "RECIBIDO",
        codigoGeneracion: "ABC123",
        selloRecibido: "SELLO",
        fhProcesamiento: "2024-01-01",
        observaciones: ["a", "b", "c", "d", "e", "f"]
      }
    });
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const peticion = await buildPeticion(sampleDte, validJws, {
      token: "t",
      clientId: "c",
      ambiente: "00"
    });
    const resumen = await sendRecepcionDTE(peticion, { token: "t", clientId: "c", ambiente: "00" });
    expect(resumen.observaciones).toHaveLength(6);
    expect(info).toHaveBeenCalledWith("Recepción DTE ->", {
      statusHttp: 200,
      estado: "RECIBIDO",
      codigoGeneracion: "ABC123",
      selloRecibido: "SELLO",
      fhProcesamiento: "2024-01-01",
      observaciones: ["a", "b", "c", "d", "e"]
    });
    info.mockRestore();
  });

  it("reintenta en 503 y termina ok", async () => {
    vi.useFakeTimers();
    const post = vi.spyOn(axios, "post");
    post
      .mockRejectedValueOnce({ response: { status: 503 } })
      .mockRejectedValueOnce({ response: { status: 503 } })
      .mockResolvedValueOnce({ status: 200, data: {} });
    const peticion = await buildPeticion(sampleDte, validJws, { token: "t", clientId: "c", ambiente: "00" });
    const promise = sendRecepcionDTE(peticion, { token: "t", clientId: "c", ambiente: "00" });
    await vi.advanceTimersByTimeAsync(500);
    await vi.advanceTimersByTimeAsync(1500);
    await promise;
    expect(post).toHaveBeenCalledTimes(3);
    vi.useRealTimers();
  });

  it("reintenta en 429 y termina ok", async () => {
    vi.useFakeTimers();
    const post = vi.spyOn(axios, "post");
    post
      .mockRejectedValueOnce({ response: { status: 429 } })
      .mockRejectedValueOnce({ response: { status: 429 } })
      .mockResolvedValueOnce({ status: 200, data: {} });
    const peticion = await buildPeticion(sampleDte, validJws, { token: "t", clientId: "c", ambiente: "00" });
    const promise = sendRecepcionDTE(peticion, { token: "t", clientId: "c", ambiente: "00" });
    await vi.advanceTimersByTimeAsync(500);
    await vi.advanceTimersByTimeAsync(1500);
    await promise;
    expect(post).toHaveBeenCalledTimes(3);
    vi.useRealTimers();
  });

  it("propaga error 400 sin incluir token", async () => {
    const token = "SECRET";
    vi.spyOn(axios, "post").mockRejectedValue({
      response: { status: 400, data: { mensaje: "malo", observaciones: ["oops"] } }
    });
    const peticion = await buildPeticion(sampleDte, validJws, { token, clientId: "c", ambiente: "00" });
    try {
      await sendRecepcionDTE(peticion, { token, clientId: "c", ambiente: "00" });
      throw new Error("should fail");
    } catch (err) {
      expect(err.message).toContain("400");
      expect(err.message).not.toContain(token);
      expect(err.observaciones).toEqual(["oops"]);
    }
  });
});
