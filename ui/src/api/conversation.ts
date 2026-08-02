import { apiClient } from './client'
import type { ConversationRead } from '../types/conversation'

export async function createConversation(projectName: string): Promise<string> {
  const { data } = await apiClient.post<{ conversation_id: string }>('/conversations', {
    project_name: projectName,
  })
  return data.conversation_id
}

export async function getConversation(conversationId: string): Promise<ConversationRead> {
  const { data } = await apiClient.get<ConversationRead>(`/conversations/${conversationId}`)
  return data
}
