/**
 * Global Zustand store — Enterprise Edition
 * Manages: auth, upload, job polling, graph data, history, UI state
 */
import { create } from 'zustand'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || ''

// Attach Bearer token to every axios request automatically
axios.interceptors.request.use((config) => {
  const token = localStorage.getItem('mindmap_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

const useStore = create((set, get) => ({
  // ── Auth state ─────────────────────────────────────────────
  user: null,           // { id, username }
  token: null,
  isAuthenticated: false,
  authLoading: false,
  authError: null,

  // ── Upload state ───────────────────────────────────────────
  documentId: null,
  fileName: null,
  uploadProgress: 0,
  isUploading: false,
  uploadError: null,

  // ── Job / pipeline state ───────────────────────────────────
  jobStatus: null,
  pipelineProgress: 0,
  statusMessage: '',
  agentResultsReceived: 0,
  totalChunks: 0,
  sseSource: null,

  // ── Graph data ─────────────────────────────────────────────
  graph: null,
  isFetchingGraph: false,

  // ── UI state ───────────────────────────────────────────────
  activeView: 'upload',
  selectedNode: null,
  searchQuery: '',
  filterCategory: null,
  hoveredNode: null,
  isHistoryOpen: false,

  // ── History state ──────────────────────────────────────────
  history: [],
  isLoadingHistory: false,

  // ── Auth actions ───────────────────────────────────────────

  initAuth: () => {
    const token = localStorage.getItem('mindmap_token')
    const userStr = localStorage.getItem('mindmap_user')
    if (token && userStr) {
      try {
        const user = JSON.parse(userStr)
        set({ token, user, isAuthenticated: true })
        // Validate token in background
        axios.get(`${API_BASE}/api/auth/me`).catch(() => {
          get().logout()
        })
      } catch {
        localStorage.removeItem('mindmap_token')
        localStorage.removeItem('mindmap_user')
      }
    }
  },

  register: async (username, password, email) => {
    set({ authLoading: true, authError: null })
    try {
      const { data } = await axios.post(`${API_BASE}/api/auth/register`, {
        username, password, email: email || undefined,
      })
      localStorage.setItem('mindmap_token', data.access_token)
      localStorage.setItem('mindmap_user', JSON.stringify(data.user))
      set({
        token: data.access_token,
        user: data.user,
        isAuthenticated: true,
        authLoading: false,
        authError: null,
      })
      return true
    } catch (err) {
      set({
        authLoading: false,
        authError: err.response?.data?.detail || 'Registration failed',
      })
      return false
    }
  },

  login: async (username, password) => {
    set({ authLoading: true, authError: null })
    try {
      const { data } = await axios.post(`${API_BASE}/api/auth/login`, {
        username, password,
      })
      localStorage.setItem('mindmap_token', data.access_token)
      localStorage.setItem('mindmap_user', JSON.stringify(data.user))
      set({
        token: data.access_token,
        user: data.user,
        isAuthenticated: true,
        authLoading: false,
        authError: null,
      })
      return true
    } catch (err) {
      set({
        authLoading: false,
        authError: err.response?.data?.detail || 'Invalid username or password',
      })
      return false
    }
  },

  logout: () => {
    localStorage.removeItem('mindmap_token')
    localStorage.removeItem('mindmap_user')
    set({
      token: null, user: null, isAuthenticated: false,
      authError: null,
      // Reset app state
      documentId: null, fileName: null, uploadProgress: 0,
      isUploading: false, uploadError: null,
      jobStatus: null, pipelineProgress: 0, statusMessage: '',
      agentResultsReceived: 0, totalChunks: 0, sseSource: null,
      graph: null, isFetchingGraph: false,
      activeView: 'upload', selectedNode: null,
      searchQuery: '', filterCategory: null,
      history: [], isHistoryOpen: false,
    })
  },

  // ── History actions ────────────────────────────────────────

  fetchHistory: async () => {
    if (!get().isAuthenticated) return
    set({ isLoadingHistory: true })
    try {
      const { data } = await axios.get(`${API_BASE}/api/v1/history`)
      set({ history: data.documents || [], isLoadingHistory: false })
    } catch {
      set({ isLoadingHistory: false })
    }
  },

  deleteFromHistory: async (documentId) => {
    try {
      await axios.delete(`${API_BASE}/api/v1/history/${documentId}`)
      set(state => ({
        history: state.history.filter(d => d.document_id !== documentId)
      }))
      return true
    } catch {
      return false
    }
  },

  loadFromHistory: async (documentId, filename) => {
    set({
      isHistoryOpen: false,
      documentId,
      fileName: filename,
      activeView: 'processing',
      jobStatus: 'completed',
      pipelineProgress: 100,
    })
    await get().fetchGraph(documentId)
  },

  setHistoryOpen: (open) => set({ isHistoryOpen: open }),

  // ── Upload actions ─────────────────────────────────────────

  uploadDocument: async (file) => {
    set({ isUploading: true, uploadError: null, uploadProgress: 0 })
    const form = new FormData()
    form.append('file', file)
    try {
      const { data } = await axios.post(`${API_BASE}/api/v1/documents/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          const pct = Math.round((e.loaded * 100) / e.total)
          set({ uploadProgress: pct })
        },
      })
      set({
        documentId: data.document_id,
        fileName: data.filename,
        isUploading: false,
        activeView: 'processing',
        jobStatus: 'pending',
        pipelineProgress: 0,
      })
      get().startSSE(data.document_id)
      // Refresh history so new doc appears immediately
      get().fetchHistory()
    } catch (err) {
      set({
        isUploading: false,
        uploadError: err.response?.data?.detail || err.message || 'Upload failed',
      })
    }
  },

  startSSE: (documentId) => {
    const existing = get().sseSource
    if (existing) existing.close()

    const token = localStorage.getItem('mindmap_token')
    const url = `${API_BASE}/api/v1/documents/${documentId}/stream`
    const source = new EventSource(url)

    source.onmessage = (event) => {
      try {
        const state = JSON.parse(event.data)
        if (state.status === 'stream_closed') { source.close(); return }

        set({
          jobStatus: state.status,
          pipelineProgress: state.progress_pct || 0,
          totalChunks: state.total_chunks || 0,
          agentResultsReceived: state.agent_results_received || 0,
          statusMessage: getStatusMessage(state),
        })

        if (state.status === 'completed') {
          source.close()
          set({ pipelineProgress: 100 })
          get().fetchGraph(documentId)
        } else if (state.status === 'failed') {
          source.close()
          set({ uploadError: state.error_message || 'Processing failed' })
        }
      } catch (e) {
        console.error('SSE parse error', e)
      }
    }

    source.onerror = () => {
      source.close()
      get().startPolling(documentId)
    }

    set({ sseSource: source })
  },

  startPolling: (documentId) => {
    const interval = setInterval(async () => {
      try {
        const { data } = await axios.get(`${API_BASE}/api/v1/documents/${documentId}/status`)
        set({
          jobStatus: data.status,
          pipelineProgress: data.progress_pct || 0,
          totalChunks: data.total_chunks || 0,
          agentResultsReceived: data.agent_results_received || 0,
          statusMessage: getStatusMessage(data),
        })
        if (data.status === 'completed') {
          clearInterval(interval)
          get().fetchGraph(documentId)
        } else if (data.status === 'failed') {
          clearInterval(interval)
        }
      } catch (e) {
        console.error('Polling error', e)
      }
    }, 2000)
  },

  fetchGraph: async (documentId) => {
    set({ isFetchingGraph: true })
    try {
      const { data } = await axios.get(`${API_BASE}/api/v1/documents/${documentId}/graph`)
      set({ graph: data, isFetchingGraph: false, activeView: 'graph' })
      // Refresh history to get updated stats
      get().fetchHistory()
    } catch (err) {
      set({ isFetchingGraph: false })
      if (err.response?.status !== 202) {
        console.error('Graph fetch error', err)
      }
    }
  },

  setSelectedNode: (node) => set({ selectedNode: node }),
  setHoveredNode:  (node) => set({ hoveredNode: node }),
  setSearchQuery:  (q)    => set({ searchQuery: q }),
  setFilterCategory: (cat) => set({ filterCategory: cat }),

  resetToUpload: () => {
    const { sseSource } = get()
    if (sseSource) sseSource.close()
    set({
      documentId: null, fileName: null, uploadProgress: 0,
      isUploading: false, uploadError: null,
      jobStatus: null, pipelineProgress: 0, statusMessage: '',
      agentResultsReceived: 0, totalChunks: 0, sseSource: null,
      graph: null, isFetchingGraph: false,
      activeView: 'upload', selectedNode: null,
      searchQuery: '', filterCategory: null,
    })
  },
}))

function getStatusMessage(state) {
  switch (state.status) {
    case 'pending':    return 'Queued for processing…'
    case 'processing':
      if (state.total_chunks > 0) {
        const agents   = state.agent_results_received || 0
        const expected = state.total_chunks  // FIX: 1 agent per chunk, not 4
        return `${agents}/${expected} chunks processed`
      }
      return 'Extracting text and splitting into chunks…'
    case 'completed':  return 'Consensus achieved — graph ready'
    case 'failed':     return 'Processing failed'
    default:           return 'Initializing pipeline…'
  }
}

export default useStore
