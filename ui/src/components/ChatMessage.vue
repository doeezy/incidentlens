<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import type { ChatMessageModel } from '../types/conversation'
import ConfidenceBadge from './ConfidenceBadge.vue'
import IncidentCard from './IncidentCard.vue'

const props = defineProps<{
  message: ChatMessageModel
}>()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

function renderMarkdown(content: string) {
  return markdown.render(content)
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <div class="flex gap-3" :class="message.role === 'USER' ? 'justify-end' : 'justify-start'">
    <div
      v-if="message.role === 'ASSISTANT'"
      class="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-600 text-xs font-bold text-white"
      aria-hidden="true"
    >
      AI
    </div>

    <div class="max-w-[min(760px,92%)]">
      <div class="mb-1 flex items-center gap-2 text-xs text-slate-400" :class="{ 'justify-end': message.role === 'USER' }">
        <span>{{ message.role === 'USER' ? 'User' : 'Assistant' }}</span>
        <span>{{ formatTime(message.createdAt) }}</span>
      </div>

      <div
        class="rounded-lg px-4 py-3 shadow-sm"
        :class="
          message.role === 'USER'
            ? 'bg-blue-600 text-white'
            : 'border border-slate-200 bg-white text-slate-800'
        "
      >
        <div v-if="message.role === 'USER'" class="whitespace-pre-wrap text-sm leading-6">
          {{ message.content }}
        </div>

        <template v-else>
          <div class="mb-3 flex flex-wrap items-center gap-2">
            <ConfidenceBadge :level="message.trace?.answer.confidence || message.incidents?.[0]?.confidence" />
            <span
              v-if="message.trace?.query.intent"
              class="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-500"
            >
              {{ message.trace.query.intent }}
            </span>
          </div>

          <div class="markdown-body text-sm" v-html="renderMarkdown(message.content)" />

          <div v-if="message.trace?.answer.references.length" class="mt-4 border-t border-slate-100 pt-3">
            <h4 class="text-xs font-semibold uppercase text-slate-400">References</h4>
            <div class="mt-2 flex flex-wrap gap-2">
              <span
                v-for="reference in message.trace.answer.references.slice(0, 6)"
                :key="`${reference.source_type}-${reference.source_id}`"
                class="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600"
                :title="reference.summary || reference.source_id"
              >
                {{ reference.source_type.toUpperCase() }}
                <template v-if="reference.label"> · {{ reference.label }}</template>
              </span>
            </div>
          </div>

          <div v-if="message.incidents?.length" class="mt-4 grid gap-3">
            <IncidentCard
              v-for="incident in message.incidents.slice(0, 3)"
              :key="incident.incident_id"
              :incident="incident"
            />
          </div>
        </template>
      </div>
    </div>

    <div
      v-if="message.role === 'USER'"
      class="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-slate-800 text-xs font-bold text-white"
      aria-hidden="true"
    >
      U
    </div>
  </div>
</template>
