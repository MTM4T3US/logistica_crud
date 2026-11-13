import type { Quality } from './store'

/**
 * Perfis de qualidade.
 * - high:   GPU dedicada folgada (RTX 3060+), até 2× DPR, bloom completo.
 * - medium: alvo para GPU intermediária (ex.: RTX 2050 / 16 GB) em 1080p — padrão.
 * - low:    fallback para GPU integrada: sem pós-processamento (antisserrilhado nativo, resolução cheia desde a 0.6.1).
 */
export const PROFILES: Record<Quality, { dpr: [number, number]; post: boolean; bloomLevels: number; msaa: number; smaa: boolean; cityBlocks: number; motes: number; facePoints: number; aberration: boolean }> = {
  high: { dpr: [1, 2], post: true, bloomLevels: 8, msaa: 4, smaa: false, cityBlocks: 56, motes: 700, facePoints: 520, aberration: true },
  // 0.6.1: SMAA (antisserrilhado barato, sem MSAA) — antes o perfil médio não tinha nenhum
  medium: { dpr: [1, 1.25], post: true, bloomLevels: 6, msaa: 0, smaa: true, cityBlocks: 44, motes: 380, facePoints: 420, aberration: false },
  low: { dpr: [1, 1], post: false, bloomLevels: 0, msaa: 0, smaa: false, cityBlocks: 30, motes: 120, facePoints: 300, aberration: false },
}
