import type { Quality } from './store'

/**
 * Perfis de qualidade.
 * - high:   GPU dedicada folgada (RTX 3060+), até 2× DPR, bloom completo.
 * - medium: alvo para GPU intermediária (ex.: RTX 2050 / 16 GB) em 1080p — padrão.
 * - low:    fallback para GPU integrada: sem pós-processamento, resolução reduzida.
 */
export const PROFILES: Record<Quality, { dpr: [number, number]; post: boolean; bloomLevels: number; msaa: number; cityBlocks: number; motes: number; facePoints: number; aberration: boolean }> = {
  high: { dpr: [1, 2], post: true, bloomLevels: 8, msaa: 4, cityBlocks: 56, motes: 700, facePoints: 520, aberration: true },
  medium: { dpr: [1, 1.25], post: true, bloomLevels: 6, msaa: 0, cityBlocks: 44, motes: 380, facePoints: 420, aberration: false },
  low: { dpr: [0.75, 0.75], post: false, bloomLevels: 0, msaa: 0, cityBlocks: 30, motes: 120, facePoints: 300, aberration: false },
}
