<script setup lang="ts">
import { GitPullRequest, Ticket, TriangleAlert } from '@lucide/vue'
import type { IncidentSearchResult } from '../types/answer'
import ConfidenceBadge from './ConfidenceBadge.vue'

defineProps<{
  incident: IncidentSearchResult
}>()

function shortId(id: string) {
  return id.slice(0, 8)
}

function formatDate(value?: string | null) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <article class="rounded-lg border border-slate-200 bg-slate-50 p-3">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2 text-xs font-semibold text-slate-500">
          <TriangleAlert class="h-3.5 w-3.5 text-blue-600" />
          <span>INC-{{ shortId(incident.incident_id) }}</span>
          <span class="rounded bg-white px-1.5 py-0.5 text-slate-500">{{ incident.status }}</span>
        </div>
        <h4 class="mt-1 line-clamp-2 text-sm font-semibold text-slate-900">
          {{ incident.summary || incident.error_type || incident.error_message }}
        </h4>
      </div>
      <ConfidenceBadge :level="incident.confidence" />
    </div>

    <p class="mt-2 line-clamp-2 text-xs leading-5 text-slate-600">
      {{ incident.root_cause || incident.suspected_cause || incident.error_message }}
    </p>

    <div class="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
      <span>RRF #{{ incident.rrf_rank || '-' }}</span>
      <span>Score {{ incident.confidence_score.toFixed(2) }}</span>
      <span>{{ formatDate(incident.first_detected_at) }}</span>
    </div>

    <div class="mt-3 flex flex-wrap gap-2">
      <span
        v-if="incident.evidence_tickets.length"
        class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600"
      >
        <Ticket class="h-3 w-3" />
        {{ incident.evidence_tickets[0].ticket_key }}
      </span>
      <span
        v-if="incident.evidence_prs.length"
        class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600"
      >
        <GitPullRequest class="h-3 w-3" />
        {{ incident.evidence_prs[0].pr_key || 'PR' }}
      </span>
    </div>
  </article>
</template>
