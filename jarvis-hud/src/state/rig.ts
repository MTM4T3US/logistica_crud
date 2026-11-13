/**
 * Valores de animação compartilhados entre a cena 3D e o HUD.
 * Mutável e fora do React de propósito: é atualizado a cada frame pelo Director.
 */
export const rig = {
  t: 0,
  /** segundos desde o início do estado atual */
  modeT: 0,
  /** 0 = palco holográfico, 1 = mapa 3D */
  mapT: 0,
  /** núcleo reduzido no topo (rosto/mapa) */
  miniT: 0,
  faceT: 0,
  /** 0..1 quando a identidade demo é "confirmada" (tudo fica verde) */
  confirmT: 0,
  listenT: 0,
  thinkT: 0,
  speakT: 0,
  /** marcadores rosados do anel (repouso/escuta) */
  markerT: 1,
  /** nível de voz 0..1 — áudio real do assistente (ou envelope simulado na demonstração) */
  level: 0,
  /** nível do microfone 0..1 durante a escuta */
  mic: 0,
  /** 0..1 enquanto um erro é sinalizado */
  errorT: 0,
  /** multiplicador de velocidade das rotações */
  spin: 1,
  /** fator global de brilho (LUZ CINEMA/SUAVE) */
  glow: 1,
  /** progresso 0..1 do scan facial */
  scan: 0,
  /** 0 = visão alta e enevoada do mapa, 1 = órbita oblíqua sobre a cidade */
  descend: 1,
  snapped: false,
  /** malha do rosto AO VIVO (468×3, unidades da cena) vinda da câmera; null = rosto genérico */
  faceLive: null as Float32Array | null,
  /** quando faceLive foi atualizada (rig.t) — dados velhos voltam ao rosto genérico */
  faceLiveAt: -1,
  /** entrada real: progresso 0..1 e confirmação vinda do núcleo */
  faceScan: 0,
  faceOk: false,
  /** 0.7 — humor do núcleo: pulso verde (feito) e âmbar (aviso/confirmação); o vermelho é o errorT */
  okT: 0,
  warnT: 0,
  okUntil: 0,
  warnUntil: 0,
  /** 0..1: noite real em Itumbiara (mapa) e chuva agora */
  nightT: 0,
  rainT: 0,
}

export const damp = (cur: number, target: number, lambda: number, dt: number) =>
  cur + (target - cur) * (1 - Math.exp(-lambda * dt))

export const clamp01 = (x: number) => Math.min(1, Math.max(0, x))
export const smooth = (x: number) => {
  const c = clamp01(x)
  return c * c * (3 - 2 * c)
}
