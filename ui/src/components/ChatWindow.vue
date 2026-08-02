<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { ChatMessageModel } from '../types/conversation'
import ChatMessage from './ChatMessage.vue'
import LoadingIndicator from './LoadingIndicator.vue'

const props = defineProps<{
  messages: ChatMessageModel[]
  selectedProject: string | null
  loadingAnswer: boolean
  selectedTraceMessageId: string | null
  selectedIncidentId: string | null
}>()

const emit = defineEmits<{
  selectTrace: [messageId: string]
  selectIncident: [incidentId: string]
}>()

const scrollContainer = ref<HTMLElement | null>(null)

watch(
  () => [props.messages.length, props.loadingAnswer],
  async () => {
    await nextTick()
    if (!scrollContainer.value) return
    scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
  },
)
</script>

<template>
  <section class="flex min-h-[620px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-soft">
    <header class="border-b border-slate-200 px-5 py-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-slate-900">Conversation</h2>
          <p class="mt-1 text-xs text-slate-500">
            <template v-if="selectedProject">선택된 프로젝트: {{ selectedProject }}</template>
            <template v-else>프로젝트를 선택해 Conversation을 시작하세요.</template>
          </p>
        </div>
        <span
          class="rounded-full border px-3 py-1 text-xs font-medium"
          :class="
            selectedProject
              ? 'border-blue-200 bg-blue-50 text-blue-700'
              : 'border-slate-200 bg-slate-50 text-slate-500'
          "
        >
          {{ selectedProject ? 'Active' : 'Waiting' }}
        </span>
      </div>
    </header>

    <div ref="scrollContainer" class="flex-1 space-y-5 overflow-y-auto bg-slate-50/70 p-5">
      <div v-if="!messages.length" class="flex h-full min-h-[400px] items-center justify-center">
        <div class="max-w-md text-center">
          <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-lg bg-blue-50 text-lg font-bold text-blue-700">
            IL
          </div>
          <h3 class="mt-4 text-base font-semibold text-slate-900">AI Incident Agent Demo</h3>
          <p class="mt-2 text-sm leading-6 text-slate-500">
            프로젝트를 선택한 뒤 장애 증상, 에러 메시지, 해결 방법에 대해 질문하세요.
          </p>
        </div>
      </div>

      <ChatMessage
        v-for="message in messages"
        :key="message.id"
        :message="message"
        :selected-trace-message-id="selectedTraceMessageId"
        :selected-incident-id="selectedIncidentId"
        @select-trace="emit('selectTrace', $event)"
        @select-incident="emit('selectIncident', $event)"
      />

      <div v-if="loadingAnswer" class="flex items-start gap-3">
        <div class="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-600 text-xs font-bold text-white">
          AI
        </div>
        <div class="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <LoadingIndicator label="답변 생성 중" compact />
        </div>
      </div>
    </div>

    <slot />
  </section>
</template>
