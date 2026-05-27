import React, { useState, useRef, useEffect } from 'react'
import { Sparkles, BookOpen, Tag, ChevronDown, ChevronUp, Brain, ExternalLink } from 'lucide-react'
import useStore from '../store/useStore'
import AgenticMetrics from './AgenticMetrics'
import './InsightsPanel.css'

const CATEGORY_COLORS = {
  ENTITY:'#00e5ff', TECHNOLOGY:'#7c3aed', PROCESS:'#ffb300',
  CONCEPT:'#00e676', PERSON:'#ff6090', ORGANIZATION:'#ff9800',
  LOCATION:'#4fc3f7', EVENT:'#f06292', CLUSTER:'#606080', DEFAULT:'#8888aa',
}

export default function InsightsPanel({ highlightedId }) {
  const { graph } = useStore()
  const [expandedId, setExpandedId] = useState(null)
  const cardRefs   = useRef({})
  const panelRef   = useRef(null)

  // When a concept is highlighted (navigated from Graph), auto-expand + scroll + glow
  useEffect(() => {
    if (!highlightedId) return
    setExpandedId(highlightedId)

    // Small delay so the card has time to expand before scrolling
    const t = setTimeout(() => {
      const el = cardRefs.current[highlightedId]
      if (!el) return
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      // Trigger the highlight animation
      el.classList.remove('card-highlight')
      void el.offsetWidth // force reflow to restart animation
      el.classList.add('card-highlight')
      const cleanup = setTimeout(() => el.classList.remove('card-highlight'), 2600)
      return () => clearTimeout(cleanup)
    }, 350)
    return () => clearTimeout(t)
  }, [highlightedId])

  const insights = graph?.insights

  if (!insights) {
    return (
      <div className="insights-panel insights-empty">
        <div className="insights-empty-icon">🔬</div>
        <div className="insights-empty-title">Insights Unavailable</div>
        <div className="insights-empty-msg">
          Deep analysis could not be generated — likely due to API rate limits.
          The Mind Map and Graph views are unaffected.
        </div>
      </div>
    )
  }

  const paragraphs   = (insights.global_summary || '').split(/\n\n+/).filter(p => p.trim())
  const themes       = insights.themes || []
  const conceptDescs = insights.concept_descriptions || {}
  const nodes        = graph?.nodes || []

  // All nodes that have a RAG description, ranked by importance
  const conceptCards = nodes
    .filter(n => conceptDescs[n.id])
    .sort((a, b) =>
      (b.confidence * (b.mention_count || 1)) - (a.confidence * (a.mention_count || 1))
    )

  return (
    <div className="insights-panel" ref={panelRef}>
      {/* Header */}
      <div className="insights-header">
        <div className="insights-header-icon"><Sparkles size={20} /></div>
        <div>
          <div className="insights-header-title">Document Insights</div>
          <div className="insights-header-sub">Deep analysis · RAG-powered · {conceptCards.length} concepts</div>
        </div>
      </div>

      {/* Agentic Pipeline Audit — always shown first */}
      <AgenticMetrics metrics={graph?.agentic_metrics} />

      {/* Document Overview */}
      {paragraphs.length > 0 && (
        <div className="insights-section">
          <div className="insights-section-title">
            <BookOpen size={14} /><span>Document Overview</span>
          </div>
          <div className="insights-summary">
            {paragraphs.map((p, i) => (
              <p key={i} className="insights-para">{p}</p>
            ))}
          </div>
        </div>
      )}

      {/* Key Themes */}
      {themes.length > 0 && (
        <div className="insights-section">
          <div className="insights-section-title">
            <Tag size={14} /><span>Key Themes</span>
          </div>
          <div className="insights-themes">
            {themes.map((theme, i) => (
              <span key={i} className="insights-theme-chip">{theme}</span>
            ))}
          </div>
        </div>
      )}

      {/* Concept Deep Dives */}
      {conceptCards.length > 0 && (
        <div className="insights-section">
          <div className="insights-section-title">
            <Brain size={14} /><span>Concept Deep Dives</span>
            <span className="insights-count-badge">{conceptCards.length}</span>
          </div>
          <div className="insights-concepts">
            {conceptCards.map(node => {
              const isExpanded = expandedId === node.id
              const color = CATEGORY_COLORS[node.category] || CATEGORY_COLORS.DEFAULT
              const isHighlighted = highlightedId === node.id
              return (
                <div
                  key={node.id}
                  ref={el => { cardRefs.current[node.id] = el }}
                  className={`insights-concept-card ${isExpanded ? 'expanded' : ''} ${isHighlighted ? 'highlighted' : ''}`}
                  style={{ '--concept-color': color }}
                  onClick={() => setExpandedId(isExpanded ? null : node.id)}
                >
                  <div className="concept-card-header">
                    <div className="concept-card-left">
                      <div className="concept-card-dot" style={{ background: color }} />
                      <span className="concept-card-label">{node.label}</span>
                      <span className="concept-card-cat font-mono" style={{ color }}>
                        {node.category}
                      </span>
                    </div>
                    <div className="concept-card-right">
                      <span className="concept-card-conf font-mono">
                        {Math.round((node.confidence || 0) * 100)}%
                      </span>
                      {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="concept-card-body animate-fade-in">
                      {/* Full description — same source as Graph leaf nodes */}
                      <p className="concept-card-desc">{conceptDescs[node.id]}</p>
                      <div className="concept-card-meta">
                        <span>Mentioned {node.mention_count || 1}×</span>
                        {node.sentiment != null && (
                          <span className={`concept-sentiment ${
                            node.sentiment > 0.2 ? 'pos' : node.sentiment < -0.2 ? 'neg' : 'neu'
                          }`}>
                            {node.sentiment > 0.2 ? '↑ positive'
                              : node.sentiment < -0.2 ? '↓ negative'
                              : '→ neutral'}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
