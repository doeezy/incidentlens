import axios from 'axios'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 120_000,
  headers: {
    'Content-Type': 'application/json',
  },
})
