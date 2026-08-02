<script setup lang="ts">
import { AlertCircle, CheckCircle2 } from '@lucide/vue'
import { computed, onMounted, ref } from 'vue'
import { requestAnswer } from '../api/answer'
import { createConversation, getConversation } from '../api/conversation'
import { getProjects } from '../api/project'
import ChatWindow from '../components/ChatWindow.vue'
import LoadingIndicator from '../components/LoadingIndicator.vue'
import MessageInput from '../components/MessageInput.vue'
import ProjectSelector from '../components/ProjectSelector.vue'
import TracePanel from '../components/TracePanel.vue'
import type { IncidentAgentResponse, IncidentSearchResult } from '../types/answer'
import type { ChatMessageModel, ConversationMessageRead } from '../types/conversation'
import type { AgentTrace } from '../types/trace'
import { formatTime } from '../utils/format'

type ToastState = {
  type: 'success' | 'error'
  message: string
}

const projects = ref<string[]>([])
const selectedProject = ref<string | null>(null)
const conversationId = ref<string | null>(null)
const messages = ref<ChatMessageModel[]>([])
const lastAnswerResults = ref<Record<string, IncidentSearchResult[]>>({})
const selectedTraceMessageId = ref<string | null>(null)
const selectedIncidentId = ref<string | null>(null)

const loadingProjects = ref(true)
const creatingConversation = ref(false)
const loadingAnswer = ref(false)
const toast = ref<ToastState | null>(null)

const latestTrace = computed<AgentTrace | null>(() => {
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const message = messages.value[index]
    if (message.role === 'ASSISTANT' && message.trace) return message.trace
  }
  return null
})

const selectedTraceMessage = computed<ChatMessageModel | null>(() => {
  if (selectedTraceMessageId.value) {
    const selected = messages.value.find(
      (message) => message.id === selectedTraceMessageId.value && message.role === 'ASSISTANT',
    )
    if (selected?.trace) return selected
  }

  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const message = messages.value[index]
    if (message.role === 'ASSISTANT' && message.trace) return message
  }
  return null
})

const selectedTrace = computed<AgentTrace | null>(() => selectedTraceMessage.value?.trace || null)

const selectedTraceLabel = computed(() => {
  if (!selectedTraceMessage.value) return '표시할 Trace 없음'
  return `${formatTime(selectedTraceMessage.value.createdAt)} Assistant 답변 기준`
})

const selectedTraceQuestion = computed(() => selectedTrace.value?.query.original_query || null)

const inputDisabled = computed(
  () => !conversationId.value || creatingConversation.value || loadingAnswer.value,
)

onMounted(() => {
  loadProjects()
})

async function loadProjects() {
  loadingProjects.value = true
  try {
    projects.value = await getProjects()
    if (!projects.value.length) {
      showToast('error', '조회 가능한 프로젝트가 없습니다.')
    }
  } catch {
    showToast('error', '프로젝트 조회에 실패했습니다. 백엔드 실행 상태를 확인해주세요.')
  } finally {
    loadingProjects.value = false
  }
}

async function selectProject(project: string) {
  if (project === selectedProject.value && conversationId.value) return
  if (creatingConversation.value) return
  creatingConversation.value = true
  try {
    const id = await createConversation(project)
    resetConversationState()
    conversationId.value = id
    selectedProject.value = project
    showToast('success', `${project} Conversation이 생성되었습니다.`)
  } catch {
    showToast('error', 'Conversation 생성에 실패했습니다.')
  } finally {
    creatingConversation.value = false
  }
}

async function submitQuestion(question: string) {
  if (!conversationId.value) {
    showToast('error', '먼저 프로젝트를 선택해주세요.')
    return
  }

  const pendingUserMessage: ChatMessageModel = {
    id: `local-user-${Date.now()}`,
    role: 'USER',
    content: question,
    createdAt: new Date().toISOString(),
  }

  messages.value = [...messages.value, pendingUserMessage]
  loadingAnswer.value = true

  try {
    const answer = await requestAnswer({
      conversationId: conversationId.value,
      question,
      topK: 3,
    })

    await syncConversation(answer)
  } catch {
    messages.value = messages.value.filter((message) => message.id !== pendingUserMessage.id)
    showToast('error', 'Answer 생성에 실패했습니다.')
  } finally {
    loadingAnswer.value = false
  }
}

async function syncConversation(answer: IncidentAgentResponse) {
  if (!conversationId.value) return

  const conversation = await getConversation(conversationId.value)
  selectedProject.value = conversation.project_name

  const assistantMessages = conversation.messages.filter((message) => message.role === 'ASSISTANT')
  const latestAssistant = assistantMessages[assistantMessages.length - 1]
  if (latestAssistant) {
    lastAnswerResults.value = {
      ...lastAnswerResults.value,
      [latestAssistant.id]: answer.search_results,
    }
    selectedTraceMessageId.value = latestAssistant.id
    selectedIncidentId.value =
      latestAssistant.trace_json?.confidence.selected_incident_id ||
      latestAssistant.trace_json?.answer.incident_id ||
      null
  }

  messages.value = conversation.messages.map(toChatMessage)
}

function toChatMessage(message: ConversationMessageRead): ChatMessageModel {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    createdAt: message.created_at,
    trace: message.trace_json,
    incidents: message.role === 'ASSISTANT' ? lastAnswerResults.value[message.id] || [] : undefined,
  }
}

function showToast(type: ToastState['type'], message: string) {
  toast.value = { type, message }
  window.setTimeout(() => {
    if (toast.value?.message === message) toast.value = null
  }, 3500)
}

function selectTrace(messageId: string) {
  selectedTraceMessageId.value = messageId
  selectedIncidentId.value = null
}

function selectIncident(incidentId: string) {
  selectedIncidentId.value = selectedIncidentId.value === incidentId ? null : incidentId
}

function resetConversationState() {
  conversationId.value = null
  messages.value = []
  lastAnswerResults.value = {}
  selectedTraceMessageId.value = null
  selectedIncidentId.value = null
}
</script>

<template>
  <main class="min-h-screen bg-slate-50">
    <div class="mx-auto flex w-full max-w-[1500px] flex-col gap-5 px-4 py-5 sm:px-6 lg:px-8">
      <header class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p class="text-sm font-semibold text-blue-700">IncidentLens</p>
            <h1 class="mt-1 text-2xl font-bold text-slate-950 sm:text-3xl">AI Incident Search Agent</h1>
            <p class="mt-2 text-sm text-slate-500">
              사내 장애 사례를 검색하고 해결 방법을 찾는 AI Agent
            </p>
          </div>

          <div v-if="selectedProject" class="flex flex-wrap items-center gap-2">
            <span class="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-blue-700">
              {{ selectedProject }}
            </span>
          </div>
        </div>
      </header>

      <ProjectSelector
        :projects="projects"
        :selected-project="selectedProject"
        :loading="loadingProjects"
        :creating="creatingConversation"
        @select="selectProject"
        @retry="loadProjects"
      />

      <div
        v-if="creatingConversation"
        class="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3"
      >
        <LoadingIndicator label="Conversation 생성 중" compact />
      </div>

      <div class="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(340px,0.52fr)]">
        <ChatWindow
          :messages="messages"
          :selected-project="selectedProject"
          :loading-answer="loadingAnswer"
          :selected-trace-message-id="selectedTraceMessage?.id || null"
          :selected-incident-id="selectedIncidentId"
          @select-trace="selectTrace"
          @select-incident="selectIncident"
        >
          <MessageInput
            :disabled="inputDisabled"
            :placeholder="
              selectedProject
                ? '예: 로그인에서 JwtTokenProvider ClassNotFoundException이 발생했는데 원인이 뭐야?'
                : '프로젝트를 먼저 선택하세요'
            "
            @submit="submitQuestion"
          />
        </ChatWindow>

        <TracePanel
          :trace="selectedTrace || latestTrace"
          :trace-label="selectedTraceLabel"
          :trace-question="selectedTraceQuestion"
          :project-name="selectedProject"
          :selected-incident-id="selectedIncidentId"
        />
      </div>
    </div>

    <div
      v-if="toast"
      class="fixed right-4 top-4 z-50 flex max-w-sm items-start gap-3 rounded-lg border bg-white p-4 shadow-soft"
      :class="toast.type === 'error' ? 'border-rose-200' : 'border-emerald-200'"
      role="status"
    >
      <AlertCircle v-if="toast.type === 'error'" class="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
      <CheckCircle2 v-else class="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
      <p class="text-sm leading-5 text-slate-700">{{ toast.message }}</p>
    </div>
  </main>
</template>
