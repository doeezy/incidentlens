export function formatScore(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined) return '-'
  return value.toFixed(digits)
}

export function formatConfidenceScore(value: number | null | undefined): string {
  return formatScore(value, 2)
}

export function formatDurationMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-'
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`
  return `${Math.round(value)} ms`
}

export function shortId(id?: string | null, length = 8): string {
  return id ? id.slice(0, length) : '-'
}

export function formatTime(value: string): string {
  return new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
