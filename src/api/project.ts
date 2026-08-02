import { apiClient } from './client'

export type ProjectListResponse = {
  projects: string[]
}

export async function getProjects(): Promise<string[]> {
  const { data } = await apiClient.get<ProjectListResponse>('/projects')
  return data.projects
}
