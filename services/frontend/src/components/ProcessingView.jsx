import React, { useEffect, useRef } from 'react'
import { Activity, Cpu, GitMerge, Database, CheckCircle2, AlertCircle } from 'lucide-react'
import useStore from '../store/useStore'
import './ProcessingView.css'

const PIPELINE_STAGES = [
  { id: 'ingest',       label: 'Document Ingestion',   icon: Database,   desc: 'PDF/text extraction' },
  { id: 'orchestrator', label: 'Orchestrator Agent',   icon: Cpu,        desc: 'Classify domain → decide strategy' },
  { id: 'chunk',        label: 'Chunking Service',     icon: Activity,   desc: 'Sentence-aware splitting + fan-out' },
  { id: 'agents',       label: 'Unified Agents (ReAct)',icon: Cpu,       desc: 'Think → Act → Observe → Critic', multi: true },
  { id: 'consensus',    label: 'Consensus Engine',     icon: GitMerge,   desc: 'Weighted voting & merge' },
  { id: 'graph',        label: 'Graph Builder',        icon: Database,   desc: 'Knowledge graph storage' },
]

const AGENT_NAMES = ['ReAct', 'Critic', 'Consensus', 'Orchestrator']
const AGENT_COLORS = ['#00e5ff', '#7c3aed', '#ffb300', '#00e676']

export default function ProcessingView() {
  const {
    fileName, pipelineProgress, statusMessage,
    totalChunks, agentResultsReceived, jobStatus,
  } = useStore()

  const progress = pipelineProgress || 0
  const activeStageIdx = getActiveStage(progress, jobStatus)

  return (
    <div className="processing-view animate-fade-in">
      <div className="processing-container">
        {/* Header */}
        <div className="proc-header">
          <div className="proc-title">Processing Pipeline</div>
          <div className="proc-filename font-mono">{fileName}</div>
        </div>

        {/* Progress ring + pct */}
        <div className="proc-ring-wrap">
          <ProgressRing progress={progress} status={jobStatus} />
        </div>

        {/* Status message */}
        <div className="proc-status-msg">{statusMessage}</div>

        {/* Chunk / agent stats */}
        {totalChunks > 0 && (
          <div className="proc-stats">
            <div className="proc-stat">
              <span className="stat-num font-mono">{totalChunks}</span>
              <span className="stat-lbl">Chunks</span>
            </div>
            <div className="proc-stat-divider" />
            <div className="proc-stat">
              <span className="stat-num font-mono">{agentResultsReceived}</span>
              <span className="stat-lbl">Agent Results</span>
            </div>
            <div className="proc-stat-divider" />
            <div className="proc-stat">
              <span className="stat-num font-mono">{totalChunks * 4}</span>
              <span className="stat-lbl">Expected</span>
            </div>
          </div>
        )}

        {/* Pipeline stages */}
        <div className="pipeline-stages">
          {PIPELINE_STAGES.map((stage, idx) => {
            const isDone   = idx < activeStageIdx
            const isActive = idx === activeStageIdx
            const isPending= idx > activeStageIdx

            return (
              <React.Fragment key={stage.id}>
                <div className={`stage-row ${isDone ? 'done' : ''} ${isActive ? 'active' : ''} ${isPending ? 'pending' : ''}`}>
                  <div className="stage-icon-wrap">
                    {isDone
                      ? <CheckCircle2 size={16} className="icon-done" />
                      : <stage.icon size={16} className={isActive ? 'icon-active animate-pulse-glow' : 'icon-pending'} />
                    }
                  </div>
                  <div className="stage-info">
                    <div className="stage-label">{stage.label}</div>
                    <div className="stage-desc font-mono">{stage.desc}</div>
                  </div>
                  {stage.multi && isActive && (
                    <div className="agent-pills">
                      {AGENT_NAMES.map((name, i) => (
                        <AgentPill key={name} name={name} color={AGENT_COLORS[i]} active />
                      ))}
                    </div>
                  )}
                  {stage.multi && isDone && (
                    <div className="agent-pills">
                      {AGENT_NAMES.map((name, i) => (
                        <AgentPill key={name} name={name} color={AGENT_COLORS[i]} done />
                      ))}
                    </div>
                  )}
                </div>
                {idx < PIPELINE_STAGES.length - 1 && (
                  <div className={`stage-connector ${isDone ? 'done' : ''}`} />
                )}
              </React.Fragment>
            )
          })}
        </div>

        {/* Distributed systems note */}
        <div className="ds-note font-mono">
          <span className="ds-icon">⚡</span>
          Orchestrator classifies document domain before chunks dispatch.
          Each Unified Agent runs a ReAct loop (Think → Act → Observe) and an intra-chunk Critic.
          Cascade fallback: Gemini → Groq → Ollama. Fault-tolerant with DLQ + timeout watchdog.
        </div>
      </div>
    </div>
  )
}

function ProgressRing({ progress, status }) {
  const r = 54
  const circ = 2 * Math.PI * r
  const offset = circ - (progress / 100) * circ
  const isError = status === 'failed'

  return (
    <div className="progress-ring">
      <svg width="128" height="128" viewBox="0 0 128 128">
        <circle cx="64" cy="64" r={r} fill="none" stroke="var(--border-subtle)" strokeWidth="8" />
        <circle
          cx="64" cy="64" r={r} fill="none"
          stroke={isError ? 'var(--accent-red)' : 'var(--accent-cyan)'}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          transform="rotate(-90 64 64)"
          style={{ transition: 'stroke-dashoffset 0.6s var(--ease-out)', filter: isError ? 'none' : 'drop-shadow(0 0 6px rgba(0,229,255,0.6))' }}
        />
      </svg>
      <div className="ring-center">
        {isError
          ? <AlertCircle size={24} color="var(--accent-red)" />
          : <span className="ring-pct font-mono">{Math.round(progress)}%</span>
        }
      </div>
    </div>
  )
}

function AgentPill({ name, color, active, done }) {
  return (
    <div
      className={`agent-pill ${active ? 'pill-active' : ''} ${done ? 'pill-done' : ''}`}
      style={{ '--pill-color': color }}
    >
      {active && <span className="pill-blink" />}
      <span>{name}</span>
    </div>
  )
}

function getActiveStage(progress, status) {
  if (status === 'completed') return 6
  if (progress < 5)  return 0
  if (progress < 15) return 1
  if (progress < 25) return 2
  if (progress < 80) return 3
  if (progress < 95) return 4
  return 5
}
