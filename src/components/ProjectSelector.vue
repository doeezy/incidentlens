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

    <div v-if="loading" class="mt-4 flex flex-wrap gap-2">
      <div v-for="index in 3" :key="index" class="h-9 w-32 animate-pulse rounded-md bg-slate-100" />
    </div>

    <div v-else class="mt-4 flex flex-wrap gap-2">
      <button
        v-for="project in projects"
        :key="project"
        type="button"
        class="rounded-md border px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60"
        :class="
          selectedProject === project
            ? 'border-blue-600 bg-blue-600 text-white shadow-sm'
            : 'border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700'
        "
        :disabled="creating"
        @click="emit('select', project)"
      >
        {{ project }}
      </button>
    </div>
  </section>
</template>
