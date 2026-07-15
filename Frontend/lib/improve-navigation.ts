import type { ExactImproveTarget } from './api'

export function normalizeImproveMode(mode?: string | null): 'interview' | 'technical' {
  return String(mode || '').toLowerCase() === 'technical' ? 'technical' : 'interview'
}

export function isExactImproveTarget(value: Partial<ExactImproveTarget> | null | undefined): value is ExactImproveTarget {
  return Boolean(value?.mission_id && value?.roadmap_node_id && value?.exercise_id)
}

export function buildImproveUrl(target?: Partial<ExactImproveTarget> | null): string {
  const params = new URLSearchParams({ tab: 'improve' })
  if (target?.mode) params.set('mode', normalizeImproveMode(target.mode))
  if (target?.mission_id) params.set('mission_id', target.mission_id)
  if (target?.roadmap_node_id) params.set('roadmap_node_id', target.roadmap_node_id)
  if (target?.exercise_id) params.set('exercise_id', target.exercise_id)
  return `/?${params.toString()}`
}

export function readImproveTarget(params: URLSearchParams): ExactImproveTarget | null {
  const candidate: Partial<ExactImproveTarget> = {
    mode: params.get('mode'),
    mission_id: params.get('mission_id') || '',
    roadmap_node_id: params.get('roadmap_node_id') || '',
    exercise_id: params.get('exercise_id') || '',
  }
  return isExactImproveTarget(candidate) ? candidate : null
}
