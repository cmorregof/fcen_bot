// Configuración de despliegue de MemorIA en Railway (Infrastructure as Code).
// Reemplaza a railway.toml (Config as Code), que Railway deja de leer el 2026-12-01.
//
// Railway NO lee este archivo al desplegar: solo se aplica con
// `railway config plan` (revisar) y `railway config apply` (aplicar).
// El archivo describe el proyecto completo: un servicio, base o volumen que
// no aparezca aquí, `apply` lo marca para borrarlo. Al crear un servicio nuevo
// (por ejemplo admisión), agréguelo aquí antes del siguiente `apply`.
//
// Las variables no las gestiona este archivo (`variables: { managed: false }`):
// se siguen configurando en la pestaña Variables de cada servicio.
//
// Generado con `railway config migrate --variables unmanaged --show` (CLI 5.71)
// y ajustado a mano: política de reinicio explícita y fcen_bot sin commit fijo.
// Detalle en docs/despliegue-servicios.md.
import { defineRailway, github, postgres, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const fcen_bot = github("cmorregof/fcen_bot", { branch: "main", checkSuites: false });

  // Lo que antes estaba en railway.toml, igual para los tres servicios.
  // El healthcheck es crítico: /health responde 503 si falta el volumen o
  // Postgres no responde, y así Railway no reemplaza el despliegue vivo.
  const build = { buildEnvironment: "V3", builder: "DOCKERFILE" } as const;
  const deploy = { restartPolicyType: "ON_FAILURE", restartPolicyMaxRetries: 10 } as const;
  const healthcheck = "/health";
  const healthcheckTimeout = 300;

  const Postgres = postgres("Postgres", { region: "us-west2" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const fcenOportunidadesVolume = volume("fcen-oportunidades-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 50000 });
  const fcenCalidadVolume = volume("fcen-calidad-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 5000 });
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 50000 });
  const fcen_botVolume = volume("fcen_bot-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 5000 });

  const fcenCalidad = service("fcen-calidad", {
    source: fcen_bot,
    build,
    deploy,
    healthcheck,
    healthcheckTimeout,
    replicas: { "us-west2": 1 },
    volumeMounts: { "/data": fcenCalidadVolume },
  });
  const fcenOportunidades = service("fcen-oportunidades", {
    source: fcen_bot,
    build,
    deploy,
    healthcheck,
    healthcheckTimeout,
    replicas: { "us-west2": 1 },
    volumeMounts: { "/data": fcenOportunidadesVolume },
  });
  // Servicio de actas.
  const fcen_bot2 = service("fcen_bot", {
    source: fcen_bot,
    build,
    deploy,
    healthcheck,
    healthcheckTimeout,
    replicas: { "us-west2": 1 },
    networking: { privateNetworkEndpoint: "fcenbot" },
    volumeMounts: { "/data": fcen_botVolume },
  });

  return project("fcen-bot", {
    variables: { managed: false },
    resources: [fcenCalidad, Postgres, fcenOportunidades, fcen_bot2, fcenOportunidadesVolume, fcenCalidadVolume, postgresVolume, fcen_botVolume],
  });
});
