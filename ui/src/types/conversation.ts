import type { IncidentSearchResult } from './answer'
import type { AgentTrace } from './trace'

export type ConversationRole = 'USER' | 'ASSISTANT'

export type ConversationMessageRead = {
  id: string
  conversation_id: string
  role: ConversationRole
  content: string
  trace_json?: AgentTrace | null
  created_at: string
}

export type ConversationRead = {
  id: string
  project_name: string
  created_at: string
  updated_at: string
  messages: ConversationMessageRead[]
}

export type ChatMessageModel = {
  id: string
  role: ConversationRole
  content: string
  createdAt: string
  trace?: AgentTrace | null
  incidents?: IncidentSearchResult[]
}
