<script setup lang="ts">
import { ChevronDown, Database, Search, Workflow } from '@lucide/vue'
import { computed, ref } from 'vue'
import type { AgentTrace, AgentTraceCandidate } from '../types/trace'
import TraceSection from './TraceSection.vue'

const props = defineProps<{
  trace: AgentTrace | null
}>()

const expanded = ref(true)
const rawExpanded = ref(false)

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
  return [
    { label: 'Query Analyzer', value: props.trace.timing.query_analyzer_ms },
    { label: 'Retrieval', value: props.trace.timing.retrieval_ms },
    { label: 'Confidence', value: props.trace.timing.confidence_ms },
    { label: 'Answer', value: props.trace.timing.answer_generation_ms },
    { label: 'Total', value: props.trace.timing.total_ms },
  ]
})

function shortId(id?: string | null) {
  return id ? id.slice(0, 8) : '-'
}

function formatMs(value?: number | null) {
  if (value === null || value === undefined) return '-'
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`
  return `${Math.round(value)}ms`
}

function score(candidate: AgentTraceCandidate) {
  const value = candidate.rrf_score ?? candidate.bm25_score ?? candidate.vector_score ?? candidate.raw_score
  return value === null || value === undefined ? '-' : value.toFixed(4)
}

function candidates(items?: AgentTraceCandidate[]) {
  return (items || []).slice(0, 3)
}
</script>

<template>
  <aside class="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-soft">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-3 border-b border-slate-200 px-5 py-4 text-left lg:pointer-events-none"
      @click="expanded = !expanded"
    >
      <div>
        <h2 class="text-base font-semibold text-slate-900">Agent Trace</h2>
        <p class="mt-1 text-xs text-slate-500">최신 Assistant 답변 기준</p>
      </div>
      <ChevronDown class="h-4 w-4 text-slate-400 transition lg:hidden" :class="{ 'rotate-180': expanded }" />
    </button>

    <div v-show="expanded" class="max-h-[calc(100vh-156px)] overflow-y-auto">
      <div v-if="!trace" class="p-5 text-sm leading-6 text-slate-500">
        아직 표시할 Trace가 없습니다. 질문을 전송하면 Query Analyzer부터 Timing까지 최신 실행 과정이 표시됩니다.
      </div>

      <template v-else>
        <TraceSection title="Query Analyzer">
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

        <TraceSection title="Hybrid Retrieval">
          <div class="space-y-4">
            <div
              v-for="group in retrievalGroups"
              :key="group.label"
            >
              <div class="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-500">
                <component :is="group.icon" class="h-3.5 w-3.5 text-blue-600" />
                {{ group.label }}
              </div>
              <div v-if="group.items.length" class="space-y-2">
                <div
                  v-for="candidate in group.items"
                  :key="`${group.label}-${candidate.incident_id}`"
                  class="grid grid-cols-[38px_1fr_auto] items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs"
                >
                  <span class="font-semibold text-slate-500">#{{ candidate.rank }}</span>
                  <span class="truncate text-slate-700">INC-{{ shortId(candidate.incident_id) }}</span>
                  <span class="font-mono text-slate-500">{{ score(candidate) }}</span>
                </div>
              </div>
              <div v-else class="rounded-md border border-dashed border-slate-200 p-2 text-xs text-slate-400">
                후보 없음
              </div>
            </div>
          </div>
        </TraceSection>

        <TraceSection title="Batch Confidence">
          <div class="space-y-3 text-sm">
            <div>
              <div class="text-xs font-medium text-slate-400">Candidate Evaluation</div>
              <div class="mt-2 space-y-2">
                <div
                  v-for="evaluation in trace.confidence.llm_evaluations.slice(0, 3)"
                  :key="evaluation.incident_id"
                  class="rounded-md border border-slate-200 bg-slate-50 p-2"
                >
                  <div class="flex items-center justify-between gap-2 text-xs">
                    <span class="font-semibold text-slate-700">INC-{{ shortId(evaluation.incident_id) }}</span>
                    <span class="font-mono text-slate-500">{{ evaluation.confidence_score.toFixed(2) }}</span>
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
                  class="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600"
                >
                  {{ index + 1 }}. INC-{{ shortId(incidentId) }}
                </span>
                <span v-if="!trace.confidence.ranking.length" class="text-xs text-slate-400">-</span>
              </div>
            </div>
            <div>
              <div class="text-xs font-medium text-slate-400">Selected Incident</div>
              <div class="mt-1 rounded-md bg-blue-50 p-2 text-sm font-semibold text-blue-800">
                INC-{{ shortId(trace.confidence.selected_incident_id || trace.answer.incident_id) }}
              </div>
            </div>
          </div>
        </TraceSection>

        <TraceSection title="Timing">
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div
              v-for="item in timingItems"
              :key="item.label"
              class="rounded-md border border-slate-200 bg-slate-50 p-2"
            >
              <div class="text-slate-400">{{ item.label }}</div>
              <div class="mt-1 font-mono font-semibold text-slate-800">{{ formatMs(item.value) }}</div>
            </div>
          </div>
        </TraceSection>

        <section class="p-4">
          <button
            type="button"
            class="flex w-full items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            @click="rawExpanded = !rawExpanded"
          >
            Raw JSON 보기
            <ChevronDown class="h-4 w-4 transition" :class="{ 'rotate-180': rawExpanded }" />
          </button>
          <pre
            v-if="rawExpanded"
            class="mt-3 max-h-96 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100"
          >{{ rawJson }}</pre>
        </section>
      </template>
    </div>
  </aside>
</template>
