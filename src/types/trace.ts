export type ConfidenceLevel = 'high' | 'medium' | 'low'

export type AgentTraceCandidate = {
  search_type: 'VECTOR' | 'BM25' | 'RRF'
  incident_id: string
  rank: number
  raw_score?: number | null
  vector_score?: number | null
  bm25_score?: number | null
  rrf_score?: number | null
  distance?: number | null
  vector_rank?: number | null
  bm25_rank?: number | null
}

export type AgentTraceReference = {
  source_type: 'incident' | 'log' | 'ticket' | 'pr'
  source_id: string
  label?: string | null
  summary?: string | null
}

export type AgentTrace = {
  trace_id: string
  trace_version: string
  request_id: string
  created_at: string
  query: {
    original_query: string
    rewritten_query?: string | null
    intent?: string | null
    retrieval_required: boolean
    reason?: string | null
  }
  retrieval: {
    vector_candidate_count: number
    bm25_candidate_count: number
    rrf_candidate_count: number
    vector_candidates: AgentTraceCandidate[]
    bm25_candidates: AgentTraceCandidate[]
    rrf_candidates: AgentTraceCandidate[]
  }
  confidence: {
    batch_input_candidate_ids: string[]
    llm_evaluations: Array<{
      incident_id: string
      confidence: ConfidenceLevel
      confidence_score: number
      should_include: boolean
      reason: string
    }>
    ranking: string[]
    selected_incident_id?: string | null
    selected_incident_ids: string[]
  }
  answer: {
    incident_id?: string | null
    confidence?: ConfidenceLevel | null
    references: AgentTraceReference[]
    response: string
  }
  timing: {
    query_analyzer_ms?: number | null
    retrieval_ms?: number | null
    confidence_ms?: number | null
    answer_generation_ms?: number | null
    total_ms?: number | null
  }
}
