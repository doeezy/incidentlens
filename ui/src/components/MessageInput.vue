<script setup lang="ts">
import { SendHorizonal } from '@lucide/vue'
import { nextTick, ref } from 'vue'

const props = defineProps<{
  disabled: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  submit: [question: string]
}>()

const value = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)

function resize() {
  nextTick(() => {
    if (!textarea.value) return
    textarea.value.style.height = 'auto'
    textarea.value.style.height = `${Math.min(textarea.value.scrollHeight, 168)}px`
  })
}

function submit() {
  const question = value.value.trim()
  if (!question || props.disabled) return
  emit('submit', question)
  value.value = ''
  resize()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  submit()
}
</script>

<template>
  <form class="border-t border-slate-200 bg-white p-3" @submit.prevent="submit">
    <div class="flex items-end gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2 focus-within:border-blue-300 focus-within:bg-white focus-within:ring-4 focus-within:ring-blue-50">
      <textarea
        ref="textarea"
        v-model="value"
        class="max-h-40 min-h-11 flex-1 resize-none border-0 bg-transparent px-2 py-2 text-sm leading-6 text-slate-900 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed"
        rows="1"
        :disabled="disabled"
        :placeholder="placeholder || '장애 증상이나 에러 메시지를 입력하세요'"
        @input="resize"
        @keydown="onKeydown"
      />
      <button
        type="submit"
        class="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-blue-600 text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        :disabled="disabled || !value.trim()"
        aria-label="질문 전송"
        title="질문 전송"
      >
        <SendHorizonal class="h-4 w-4" />
      </button>
    </div>
    <p class="mt-2 text-xs text-slate-400">Enter 전송 · Shift+Enter 줄바꿈</p>
  </form>
</template>
