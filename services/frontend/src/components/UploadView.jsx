import React, { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Upload, FileText, Zap, Network, GitMerge, Layers } from 'lucide-react'
import toast from 'react-hot-toast'
import useStore from '../store/useStore'
import './UploadView.css'

const FEATURES = [
  { icon: GitMerge,  title: 'Orchestrator Agent',   desc: 'Classifies document domain and decides extraction strategy before any chunk is dispatched' },
  { icon: Layers,    title: 'ReAct Agent Loop',      desc: 'Each agent Thinks → Acts → Observes confidence → retries with adjusted strategy if needed' },
  { icon: Zap,       title: 'Intra-chunk Critic',    desc: 'A second LLM pass scores each relationship for grounding in source text, filtering weak ones' },
  { icon: Network,   title: 'Consensus + Graph',     desc: 'Weighted voting across parallel agents merges into an interactive radial mind map' },
]

export default function UploadView() {
  const { uploadDocument, isUploading, uploadError, uploadProgress } = useStore()

  const onDrop = useCallback((accepted, rejected) => {
    if (rejected.length > 0) {
      toast.error(`Unsupported file type. Use PDF, TXT, or MD.`)
      return
    }
    if (accepted.length > 0) {
      uploadDocument(accepted[0])
    }
  }, [uploadDocument])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'text/plain':       ['.txt'],
      'text/markdown':    ['.md'],
    },
    maxFiles: 1,
    maxSize: 20 * 1024 * 1024, // 20 MB
    disabled: isUploading,
  })

  return (
    <div className="upload-view animate-fade-in">
      {/* Hero */}
      <div className="upload-hero">
        <div className="hero-badge font-mono">DISTRIBUTED SYSTEM · 8 MICROSERVICES · REACT AGENTS · 3-TIER LLM CASCADE</div>
        <h1 className="hero-title">
          Turn Any Document Into a<br />
          <span className="hero-accent">Living Knowledge Graph</span>
        </h1>
        <p className="hero-desc">
          Upload a PDF or text file. Watch 4 AI agents process it in parallel,
          reach consensus, and render an interactive mind map in seconds.
        </p>
      </div>

      {/* Drop zone */}
      <div className="upload-zone-wrapper">
        <div
          {...getRootProps()}
          className={`upload-zone ${isDragActive ? 'drag-active' : ''} ${isUploading ? 'uploading' : ''}`}
        >
          <input {...getInputProps()} />
          <div className="upload-zone-inner">
            {isUploading ? (
              <>
                <div className="upload-spinner" />
                <div className="upload-progress-label">
                  Uploading<span className="upload-pct">{uploadProgress}%</span>
                </div>
                <div className="upload-bar-track">
                  <div className="upload-bar-fill" style={{ width: `${uploadProgress}%` }} />
                </div>
              </>
            ) : (
              <>
                <div className={`upload-icon-wrap ${isDragActive ? 'drag-bounce' : ''}`}>
                  <Upload size={28} />
                </div>
                <div className="upload-label">
                  {isDragActive ? 'Drop it here' : 'Drop your document or click to browse'}
                </div>
                <div className="upload-hint font-mono">PDF · TXT · MD · up to 20 MB</div>
              </>
            )}
          </div>
        </div>

        {uploadError && (
          <div className="upload-error animate-fade-in">{uploadError}</div>
        )}
      </div>

      {/* Feature cards */}
      <div className="features-grid">
        {FEATURES.map(({ icon: Icon, title, desc }) => (
          <div key={title} className="feature-card">
            <div className="feature-icon"><Icon size={18} /></div>
            <div className="feature-title">{title}</div>
            <div className="feature-desc">{desc}</div>
          </div>
        ))}
      </div>

      {/* Architecture hint */}
      <div className="arch-hint font-mono">
        <span className="arch-item">API Gateway</span>
        <span className="arch-arrow">→</span>
        <span className="arch-item">Ingestion</span>
        <span className="arch-arrow">→</span>
        <span className="arch-item highlight">Orchestrator</span>
        <span className="arch-arrow">→</span>
        <span className="arch-item accent">Chunker</span>
        <span className="arch-arrow">→</span>
        <span className="arch-item highlight">ReAct Agents</span>
        <span className="arch-arrow">→</span>
        <span className="arch-item accent">Consensus</span>
        <span className="arch-arrow">→</span>
        <span className="arch-item">Graph Builder</span>
      </div>
    </div>
  )
}
