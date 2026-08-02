<script setup lang="ts">
import { GitPullRequest, Ticket, TriangleAlert } from '@lucide/vue'
import type { IncidentSearchResult } from '../types/answer'
import { formatConfidenceScore, formatTime, shortId } from '../utils/format'
import ConfidenceBadge from './ConfidenceBadge.vue'

defineProps<{
  incident: IncidentSearchResult
  selected: boolean
}>()

function formatDate(value?: string | null) {
  if (!value) return '-'
  return formatTime(value)
}
</script>

<template>
  <button
    type="button"
    class="w-full rounded-lg border p-3 text-left transition focus:outline-none focus:ring-4 focus:ring-blue-50"
    :class="
      selected
        ? 'border-blue-300 bg-blue-50 shadow-sm'
        : 'border-slate-200 bg-slate-50 hover:border-blue-200 hover:bg-white'
    "
    :aria-pressed="selected"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2 text-xs font-semibold text-slate-500">
          <TriangleAlert class="h-3.5 w-3.5 text-blue-600" />
          <span>INC-{{ shortId(incident.incident_id) }}</span>
          <span class="rounded bg-white px-1.5 py-0.5 text-slate-500">{{ incident.status }}</span>
          <span v-if="selected" class="rounded bg-blue-600 px-1.5 py-0.5 text-white">Selected</span>
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
      <span>Score {{ formatConfidenceScore(incident.confidence_score) }}</span>
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
  </button>
</template>
