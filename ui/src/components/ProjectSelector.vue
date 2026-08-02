<script setup lang="ts">
import { RefreshCw } from '@lucide/vue'

defineProps<{
  projects: string[]
  selectedProject: string | null
  loading: boolean
  creating: boolean
}>()

const emit = defineEmits<{
  select: [project: string]
  retry: []
}>()

function onChange(event: Event) {
  const project = (event.target as HTMLSelectElement).value
  if (!project) return
  emit('select', project)
}
</script>

<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold text-slate-900">Project</h2>
        <p class="mt-1 text-xs text-slate-500">
          검색 범위를 선택하면 새 Conversation이 생성됩니다.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 text-slate-500 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="loading || creating"
        aria-label="프로젝트 다시 조회"
        title="프로젝트 다시 조회"
        @click="emit('retry')"
      >
        <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
      </button>
    </div>

    <div v-if="loading" class="mt-4">
      <div class="h-11 w-full max-w-sm animate-pulse rounded-md bg-slate-100" />
    </div>

    <div v-else class="mt-4 max-w-sm">
      <label class="sr-only" for="project-select">프로젝트 선택</label>
      <select
        id="project-select"
        class="h-11 w-full rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-800 outline-none transition focus:border-blue-300 focus:ring-4 focus:ring-blue-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
        :value="selectedProject || ''"
        :disabled="creating || !projects.length"
        @change="onChange"
      >
        <option value="" disabled>프로젝트를 선택하세요</option>
        <option v-for="project in projects" :key="project" :value="project">
          {{ project }}
        </option>
      </select>
      <p v-if="!projects.length" class="mt-2 text-xs text-slate-500">
        선택 가능한 프로젝트가 없습니다.
      </p>
    </div>
  </section>
</template>
