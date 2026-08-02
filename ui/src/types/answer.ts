import type { ConfidenceLevel } from './trace'

export type EvidenceTicket = {
  id: string
  ticket_key: string
  title: string
  description?: string | null
  status?: string | null
  priority?: string | null
  reporter?: string | null
  assignee?: string | null
  normalized_summary?: string | null
  suspected_cause?: string | null
  resolution_note?: string | null
  ticket_created_at: string
}

export type EvidencePr = {
  id: string
  pr_key?: string | null
  title: string
  description?: string | null
  author?: string | null
  status?: string | null
  source_branch?: string | null
  target_branch?: string | null
  changed_files?: string[] | null
  diff_summary?: string | null
  normalized_summary?: string | null
  suspected_fix_for?: string | null
  resolution_note?: string | null
  merged_at?: string | null
}

export type EvidenceLog = {
  id: string
  log_level?: string | null
  raw_message: string
  error_type?: string | null
  error_message?: string | null
  normalized_summary?: string | null
  occurred_at: string
}

export type IncidentSearchResult = {
  incident_id: string
  score: number
  distance?: number | null
  vector_rank?: number | null
  keyword_rank?: number | null
  rrf_rank?: number | null
  vector_score?: number | null
  bm25_score?: number | null
  rrf_score: number
  confidence: ConfidenceLevel
  confidence_score: number
  confidence_reason: string
  project_name: string
  status: string
  first_detected_at: string
  last_seen_at?: string | null
  resolved_at?: string | null
  summary?: string | null
  error_type?: string | null
  error_message: string
  root_cause?: string | null
  suspected_cause?: string | null
  resolution?: string | null
  keywords?: string[] | null
  domain_tags?: string[] | null
  evidence_logs: EvidenceLog[]
  evidence_tickets: EvidenceTicket[]
  evidence_prs: EvidencePr[]
}

export type IncidentAgentResponse = {
  question: string
  project_name?: string | null
  intent: 'ROOT_CAUSE' | 'RESOLUTION' | 'SIMILAR_CASE' | 'SUMMARY' | 'OUT_OF_SCOPE'
  retrieval_required: boolean
  rewritten_query?: string | null
  analysis_reason: string
  answer: string
  search_results: IncidentSearchResult[]
}
