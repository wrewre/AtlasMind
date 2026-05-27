/**
 * AgenticMetrics — displays the agentic pipeline audit trail
 *
 * Data source: graph.agentic_metrics (populated by consensus engine)
 * Shows:
 *   - LLM usage breakdown (which model processed how many chunks)
 *   - Extraction strategy distribution (relationship_first / concept_first / balanced)
 *   - ReAct loop stats (avg iterations, retry count)
 *   - Critic impact (how many relationships were filtered for low grounding)
 *   - Orchestrator decision (domain + strategy + who decided it)
 *   - Fallback rate (% chunks that used Groq or Ollama instead of Gemini)
 */
import React, { useState } from 'react'
import { Bot, Zap, Shield, GitBranch, BarChart2, ChevronDown, ChevronUp } from 'lucide-react'
import './AgenticMetrics.css'

const LLM_COLORS = {
  gemini: '#00e5ff',
  groq:   '#7c3aed',
  ollama: '#00e676',
  cache:  '#ffb300',
  unknown:'#555577',
}

const STRATEGY_COLORS = {
  relationship_first: '#00e5ff',
  concept_first:      '#ffb300',
  balanced:           '#00e676',
  none:               '#555577',
}

const DOMAIN_EMOJI = {
  technical:  '⚙️',
  scientific: '🔬',
  legal:      '⚖️',
  narrative:  '📖',
  general:    '📄',
}

function MiniBar({ value, max, color, label, count }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="am-bar-row">
      <div className="am-bar-label font-mono">{label}</div>
      <div className="am-bar-track">
        <div
          className="am-bar-fill"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <div className="am-bar-count font-mono">{count}</div>
    </div>
  )
}

function StatPill({ label, value, accent, title }) {
  return (
    <div className="am-stat-pill" title={title}>
      <div className="am-stat-value font-mono" style={{ color: accent }}>{value}</div>
      <div className="am-stat-label">{label}</div>
    </div>
  )
}

export default function AgenticMetrics({ metrics }) {
  const [expanded, setExpanded] = useState(true)

  if (!metrics) return null

  const {
    llm_usage              = {},
    strategy_usage         = {},
    avg_react_iterations   = 1,
    react_retry_count      = 0,
    total_critic_filtered  = 0,
    avg_processing_ms      = 0,
    fallback_rate_pct      = 0,
    domain                 = 'general',
    orchestrator_strategy  = 'balanced',
    orchestrator_decided_by= 'unknown',
  } = metrics

  const totalChunks    = Object.values(llm_usage).reduce((a, b) => a + b, 0)
  const totalStrategies= Object.values(strategy_usage).reduce((a, b) => a + b, 0)
  const primaryLLM     = Object.entries(llm_usage).sort((a,b) => b[1]-a[1])[0]?.[0] || 'none'
  const usedFallback   = (llm_usage.groq || 0) + (llm_usage.ollama || 0) > 0

  return (
    <div className="agentic-metrics">
      {/* Header — always visible */}
      <div className="am-header" onClick={() => setExpanded(e => !e)}>
        <div className="am-header-left">
          <div className="am-header-icon"><Bot size={16} /></div>
          <div>
            <div className="am-header-title">Agentic Pipeline Audit</div>
            <div className="am-header-sub font-mono">
              {totalChunks} chunks · {primaryLLM} primary · {fallback_rate_pct}% fallback
            </div>
          </div>
        </div>
        <div className="am-header-right">
          {usedFallback && (
            <span className="am-badge am-badge-fallback">cascade triggered</span>
          )}
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </div>

      {expanded && (
        <div className="am-body animate-fade-in">

          {/* Orchestrator Decision */}
          <div className="am-section">
            <div className="am-section-title">
              <GitBranch size={13} /><span>Orchestrator Decision</span>
            </div>
            <div className="am-orchestrator-row">
              <div className="am-orch-domain">
                <span className="am-orch-emoji">{DOMAIN_EMOJI[domain] || '📄'}</span>
                <div>
                  <div className="am-orch-domain-label">{domain}</div>
                  <div className="am-orch-domain-sub font-mono">document domain</div>
                </div>
              </div>
              <div className="am-orch-arrow">→</div>
              <div className="am-orch-strategy">
                <div
                  className="am-orch-strategy-label"
                  style={{ color: STRATEGY_COLORS[orchestrator_strategy] || '#8888aa' }}
                >
                  {orchestrator_strategy.replace(/_/g, ' ')}
                </div>
                <div className="am-orch-strategy-sub font-mono">extraction strategy</div>
              </div>
              <div className="am-orch-decided font-mono">
                via {orchestrator_decided_by}
              </div>
            </div>
          </div>

          {/* LLM Usage */}
          <div className="am-section">
            <div className="am-section-title">
              <Zap size={13} /><span>LLM Usage per Chunk</span>
            </div>
            <div className="am-bars">
              {Object.entries(llm_usage)
                .sort((a, b) => b[1] - a[1])
                .map(([llm, count]) => (
                  <MiniBar
                    key={llm}
                    label={llm}
                    value={count}
                    max={totalChunks}
                    color={LLM_COLORS[llm] || LLM_COLORS.unknown}
                    count={count}
                  />
                ))}
            </div>
            <div className="am-llm-legend">
              <span className="am-legend-item">
                <span className="am-legend-dot" style={{ background: LLM_COLORS.gemini }} />
                Gemini (primary)
              </span>
              <span className="am-legend-item">
                <span className="am-legend-dot" style={{ background: LLM_COLORS.groq }} />
                Groq (fallback)
              </span>
              <span className="am-legend-item">
                <span className="am-legend-dot" style={{ background: LLM_COLORS.ollama }} />
                Ollama (local fallback)
              </span>
            </div>
          </div>

          {/* Strategy Distribution */}
          <div className="am-section">
            <div className="am-section-title">
              <BarChart2 size={13} /><span>Extraction Strategy per Chunk</span>
            </div>
            <div className="am-bars">
              {Object.entries(strategy_usage)
                .sort((a, b) => b[1] - a[1])
                .map(([strat, count]) => (
                  <MiniBar
                    key={strat}
                    label={strat.replace(/_/g, ' ')}
                    value={count}
                    max={totalStrategies}
                    color={STRATEGY_COLORS[strat] || '#8888aa'}
                    count={count}
                  />
                ))}
            </div>
            <div className="am-strategy-note font-mono">
              Individual chunks may override the document-level strategy (e.g. reference sections → concept_first)
            </div>
          </div>

          {/* ReAct + Critic Stats */}
          <div className="am-section">
            <div className="am-section-title">
              <Shield size={13} /><span>ReAct Loop + Critic Quality Filter</span>
            </div>
            <div className="am-stats-grid">
              <StatPill
                label="Avg ReAct iterations"
                value={avg_react_iterations.toFixed(2)}
                accent="var(--accent-cyan)"
                title="Average number of Thought→Act→Observe cycles per chunk. >1 means some chunks needed a retry."
              />
              <StatPill
                label="Chunks retried"
                value={react_retry_count}
                accent={react_retry_count > 0 ? '#ffb300' : 'var(--text-muted)'}
                title="Chunks where the first extraction attempt had low confidence and the agent retried with a different strategy."
              />
              <StatPill
                label="Relationships critic-filtered"
                value={total_critic_filtered}
                accent={total_critic_filtered > 0 ? '#00e676' : 'var(--text-muted)'}
                title="Relationships removed by the Critic agent for low grounding score (< 0.5). These were extracted but not supported by the source text."
              />
              <StatPill
                label="Avg chunk time"
                value={`${avg_processing_ms}ms`}
                accent="var(--text-secondary)"
                title="Average wall-clock time per chunk including LLM call and critic pass."
              />
            </div>

            {/* Explain what ReAct means — for the teacher */}
            <div className="am-react-explain">
              <div className="am-react-step">
                <span className="am-react-badge">THINK</span>
                <span>Classify chunk type → choose extraction strategy</span>
              </div>
              <div className="am-react-arrow">→</div>
              <div className="am-react-step">
                <span className="am-react-badge">ACT</span>
                <span>Call LLM with strategy-specific prompt</span>
              </div>
              <div className="am-react-arrow">→</div>
              <div className="am-react-step">
                <span className="am-react-badge">OBSERVE</span>
                <span>Check avg confidence → retry if below threshold</span>
              </div>
              <div className="am-react-arrow">→</div>
              <div className="am-react-step">
                <span className="am-react-badge">CRITIC</span>
                <span>Score relationship grounding → filter weak ones</span>
              </div>
            </div>
          </div>

          {/* Fallback explanation */}
          {usedFallback && (
            <div className="am-fallback-note">
              <span className="am-fallback-icon">⚡</span>
              <span>
                Cascade fallback triggered during processing.{' '}
                {llm_usage.groq ? `${llm_usage.groq} chunk(s) used Groq. ` : ''}
                {llm_usage.ollama ? `${llm_usage.ollama} chunk(s) used local Ollama. ` : ''}
                Pipeline completed without interruption.
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
