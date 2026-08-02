<script setup lang="ts">
import { ChevronDown, Database, Search, Workflow } from '@lucide/vue'
import { computed, reactive, ref } from 'vue'
import type { AgentTrace, AgentTraceCandidate } from '../types/trace'
import { formatDurationMs, formatScore, shortId } from '../utils/format'
import TraceSection from './TraceSection.vue'

const props = defineProps<{
  trace: AgentTrace | null
  traceLabel: string
  traceQuestion: string | null
  projectName: string | null
  selectedIncidentId: string | null
}>()

const expanded = ref(true)
const sectionExpanded = reactive({
  query: true,
  retrieval: true,
  confidence: true,
  timing: true,
  raw: false,
})

const rawJson = computed(() => {
  if (!props.trace) return '{}'
  return JSON.stringify(props.trace, null, 2)
})

const retrievalGroups = computed(() => {
  if (!props.trace) return []
  return [
    { label: 'Vector Top3', icon: Search, items: candidates(props.trace.retrieval.vector_candidates) },
    { label: 'BM25 Top3', icon: Database, items: candidates(props.trace.retrieval.bm25_candidates) },
    { label: 'RRF Top3', icon: Workflow, items: candidates(props.trace.retrieval.rrf_candidates) },
  ]
})

const timingItems = computed(() => {
  if (!props.trace) return []
  const total = props.trace.timing.total_ms || 0
  const stages = [
    { label: 'Query Analyzer', value: props.trace.timing.query_analyzer_ms },
    { label: 'Retrieval', value: props.trace.timing.retrieval_ms },
    { label: 'Confidence', value: props.trace.timing.confidence_ms },
    { label: 'Answer Generation', value: props.trace.timing.answer_generation_ms },
  ]
  const longest = stages.reduce(
    (max, item) => ((item.value || 0) > (max.value || 0) ? item : max),
    stages[0],
  )

  return stages.map((item) => ({
    ...item,
    percent: total > 0 && item.value ? Math.min(100, Math.max(0, (item.value / total) * 100)) : 0,
    longest: item.label === longest.label && (item.value || 0) > 0,
  }))
})

const totalTiming = computed(() => props.trace?.timing.total_ms)

function candidates(items?: AgentTraceCandidate[]) {
  return (items || []).slice(0, 3)
}

function score(candidate: AgentTraceCandidate) {
  if (candidate.rrf_score !== null && candidate.rrf_score !== undefined) {
    return formatScore(candidate.rrf_score, 4)
  }
  if (candidate.bm25_score !== null && candidate.bm25_score !== undefined) {
    return formatScore(candidate.bm25_score, 3)
  }
  if (candidate.vector_score !== null && candidate.vector_score !== undefined) {
    return formatScore(candidate.vector_score, 3)
  }
  return formatScore(candidate.raw_score, 3)
}

function isSelectedIncident(incidentId?: string | null) {
  return Boolean(props.selectedIncidentId && incidentId === props.selectedIncidentId)
}

function candidateClass(incidentId: string) {
  return isSelectedIncident(incidentId)
    ? 'border-blue-300 bg-blue-50 ring-1 ring-blue-100'
    : 'border-slate-200 bg-slate-50'
}
</script>

<template>
  <aside class="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-soft">
    <button
      type="button"
      class="flex w-full items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 text-left lg:pointer-events-none"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <div class="min-w-0">
        <h2 class="text-base font-semibold text-slate-900">Agent Trace</h2>
        <div v-if="trace" class="mt-1 space-y-1">
          <p class="truncate text-xs font-medium text-slate-500">
            <span v-if="projectName">{{ projectName }} · </span>{{ traceLabel }}
          </p>
          <p class="line-clamp-2 text-sm leading-5 text-slate-700">
            {{ traceQuestion || trace.query.original_query }}
          </p>
          <p class="text-[11px] font-mono text-slate-400">trace {{ shortId(trace.trace_id) }}</p>
        </div>
        <p v-else class="mt-1 text-xs text-slate-500">{{ traceLabel }}</p>
      </div>
      <ChevronDown class="mt-1 h-4 w-4 shrink-0 text-slate-400 transition lg:hidden" :class="{ 'rotate-180': expanded }" />
    </button>

    <div v-show="expanded" class="max-h-[calc(100vh-156px)] overflow-y-auto">
      <div v-if="!trace" class="p-5 text-sm leading-6 text-slate-500">
        아직 표시할 Trace가 없습니다. 질문을 전송하면 Query Analyzer부터 Timing까지 최신 실행 과정이 표시됩니다.
      </div>

      <template v-else>
        <TraceSection
          title="Query Analyzer"
          :expanded="sectionExpanded.query"
          @toggle="sectionExpanded.query = !sectionExpanded.query"
        >
          <div class="space-y-3 text-sm">
            <div>
              <div class="text-xs font-medium text-slate-400">Original Query</div>
              <div class="mt-1 rounded-md bg-slate-50 p-2 text-slate-700">{{ trace.query.original_query }}</div>
            </div>
            <div>
              <div class="text-xs font-medium text-slate-400">Rewritten Query</div>
              <div class="mt-1 rounded-md bg-blue-50 p-2 text-blue-800">
                {{ trace.query.rewritten_query || '-' }}
              </div>
            </div>
            <div class="flex flex-wrap gap-2">
              <span class="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600">
                {{ trace.query.intent || 'UNKNOWN' }}
              </span>
              <span class="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600">
                Retrieval {{ trace.query.retrieval_required ? 'ON' : 'OFF' }}
              </span>
            </div>
          </div>
        </TraceSection>

        <TraceSection
          title="Hybrid Retrieval"
          :expanded="sectionExpanded.retrieval"
          @toggle="sectionExpanded.retrieval = !sectionExpanded.retrieval"
        >
          <div class="space-y-4">
            <div v-for="group in retrievalGroups" :key="group.label">
              <div class="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-500">
                <component :is="group.icon" class="h-3.5 w-3.5 text-blue-600" />
                {{ group.label }}
              </div>
              <div v-if="group.items.length" class="space-y-2">
                <div
                  v-for="candidate in group.items"
                  :key="`${group.label}-${candidate.incident_id}`"
                  class="grid grid-cols-[38px_1fr_auto] items-center gap-2 rounded-md border px-2.5 py-2 text-xs"
                  :class="candidateClass(candidate.incident_id)"
                >
                  <span class="font-semibold text-slate-500">#{{ candidate.rank }}</span>
                  <span class="truncate text-slate-700">INC-{{ shortId(candidate.incident_id) }}</span>
                  <div class="flex items-center gap-2">
                    <span
                      v-if="isSelectedIncident(candidate.incident_id)"
                      class="rounded bg-blue-600 px-1.5 py-0.5 text-[10px] font-bold text-white"
                    >
                      Related
                    </span>
                    <span class="font-mono text-slate-500">{{ score(candidate) }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="rounded-md border border-dashed border-slate-200 p-2 text-xs text-slate-400">
                후보 없음
              </div>
            </div>
          </div>
        </TraceSection>

        <TraceSection
          title="Batch Confidence"
          :expanded="sectionExpanded.confidence"
          @toggle="sectionExpanded.confidence = !sectionExpanded.confidence"
        >
          <div class="space-y-3 text-sm">
            <div>
              <div class="text-xs font-medium text-slate-400">Candidate Evaluation</div>
              <div class="mt-2 space-y-2">
                <div
                  v-for="evaluation in trace.confidence.llm_evaluations.slice(0, 3)"
                  :key="evaluation.incident_id"
                  class="rounded-md border p-2"
                  :class="candidateClass(evaluation.incident_id)"
                >
                  <div class="flex items-center justify-between gap-2 text-xs">
                    <span class="font-semibold text-slate-700">INC-{{ shortId(evaluation.incident_id) }}</span>
                    <div class="flex items-center gap-2">
                      <span
                        v-if="isSelectedIncident(evaluation.incident_id)"
                        class="rounded bg-blue-600 px-1.5 py-0.5 text-[10px] font-bold text-white"
                      >
                        Related
                      </span>
                      <span class="font-mono text-slate-500">{{ formatScore(evaluation.confidence_score, 2) }}</span>
                    </div>
                  </div>
                  <p class="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{{ evaluation.reason }}</p>
                </div>
                <div v-if="!trace.confidence.llm_evaluations.length" class="text-xs text-slate-400">
                  평가 결과 없음
                </div>
              </div>
            </div>
            <div>
              <div class="text-xs font-medium text-slate-400">Ranking</div>
              <div class="mt-2 flex flex-wrap gap-2">
                <span
                  v-for="(incidentId, index) in trace.confidence.ranking.slice(0, 5)"
                  :key="incidentId"
                  class="rounded-md border px-2 py-1 text-xs"
                  :class="
                    isSelectedIncident(incidentId)
                      ? 'border-blue-300 bg-blue-50 font-semibold text-blue-700'
                      : 'border-slate-200 text-slate-600'
                  "
                >
                  {{ index + 1 }}. INC-{{ shortId(incidentId) }}
                </span>
                <span v-if="!trace.confidence.ranking.length" class="text-xs text-slate-400">-</span>
              </div>
            </div>
            <div>
              <div class="text-xs font-medium text-slate-400">Selected Incident</div>
              <div
                class="mt-1 rounded-md border p-2 text-sm font-semibold"
                :class="
                  isSelectedIncident(trace.confidence.selected_incident_id || trace.answer.incident_id)
                    ? 'border-blue-300 bg-blue-50 text-blue-800'
                    : 'border-blue-100 bg-blue-50 text-blue-800'
                "
              >
                INC-{{ shortId(trace.confidence.selected_incident_id || trace.answer.incident_id) }}
                <span
                  v-if="isSelectedIncident(trace.confidence.selected_incident_id || trace.answer.incident_id)"
                  class="ml-2 rounded bg-blue-600 px-1.5 py-0.5 text-[10px] font-bold text-white"
                >
                  Selected
                </span>
              </div>
            </div>
          </div>
        </TraceSection>

        <TraceSection
          title="Timing"
          :expanded="sectionExpanded.timing"
          @toggle="sectionExpanded.timing = !sectionExpanded.timing"
        >
          <div class="space-y-3 text-xs">
            <div
              v-for="item in timingItems"
              :key="item.label"
              class="rounded-md border border-slate-200 bg-slate-50 p-3"
            >
              <div class="flex items-center justify-between gap-3">
                <div class="flex min-w-0 items-center gap-2">
                  <span class="truncate font-semibold text-slate-700">{{ item.label }}</span>
                  <span
                    v-if="item.longest"
                    class="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold text-blue-700"
                  >
                    Longest
                  </span>
                </div>
                <span class="shrink-0 font-mono text-slate-700">{{ formatDurationMs(item.value) }}</span>
              </div>
              <div v-if="totalTiming" class="mt-2 h-2 overflow-hidden rounded-full bg-slate-200">
                <div class="h-full rounded-full bg-blue-600" :style="{ width: `${item.percent}%` }" />
              </div>
            </div>

            <div class="rounded-md border border-blue-100 bg-blue-50 p-3">
              <div class="flex items-center justify-between gap-3">
                <span class="font-semibold text-blue-800">Total</span>
                <span class="font-mono font-semibold text-blue-800">{{ formatDurationMs(totalTiming) }}</span>
              </div>
            </div>
          </div>
        </TraceSection>

        <TraceSection
          title="Raw JSON"
          :expanded="sectionExpanded.raw"
          @toggle="sectionExpanded.raw = !sectionExpanded.raw"
        >
          <pre class="max-h-96 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{{ rawJson }}</pre>
        </TraceSection>
      </template>
    </div>
  </aside>
</template>
