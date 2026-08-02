import { apiClient } from './client'
import type { IncidentAgentResponse } from '../types/answer'

export async function requestAnswer(params: {
  conversationId: string
  question: string
  topK?: number
}): Promise<IncidentAgentResponse> {
  const { data } = await apiClient.post<IncidentAgentResponse>('/answers', {
    conversation_id: params.conversationId,
    question: params.question,
    top_k: params.topK ?? 3,
  })
  return data
}
