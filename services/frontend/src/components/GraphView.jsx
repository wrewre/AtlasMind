import React, { useRef, useState, useMemo } from 'react'
import {
  ZoomIn, ZoomOut, Maximize2, Search, Filter, X,
  BookOpen, ChevronRight, BarChart3, Info, Network,
  GitBranch, AlertTriangle, ChevronDown, ChevronUp, Sparkles
} from 'lucide-react'
import useStore from '../store/useStore'
import useForceGraph from '../hooks/useForceGraph'
import useMindMap    from '../hooks/useMindMap'
import InsightsPanel from './InsightsPanel'
import './GraphView.css'

const CATEGORY_COLORS = {
  ENTITY:'#00e5ff', TECHNOLOGY:'#7c3aed', PROCESS:'#ffb300',
  CONCEPT:'#00e676', PERSON:'#ff6090', ORGANIZATION:'#ff9800',
  LOCATION:'#4fc3f7', EVENT:'#f06292', CLUSTER:'#606080', DEFAULT:'#8888aa',
}

export default function GraphView() {
  const {
    graph, selectedNode, searchQuery, filterCategory,
    setSelectedNode, setSearchQuery, setFilterCategory,
  } = useStore()

  const svgRef       = useRef(null)
  const containerRef = useRef(null)
  const [viewMode, setViewMode]       = useState('mindmap')
  const [showSummary, setShowSummary] = useState(true)
  const [showStats,   setShowStats]   = useState(false)
  const [showConflicts, setShowConflicts] = useState(false)
  const [hoveredNode, setHoveredNode] = useState(null)
  const [highlightedConceptId, setHighlightedConceptId] = useState(null)

  // Force graph hooks (for Graph tab)
  const forceGraph = useForceGraph(
    svgRef,
    containerRef,
    graph,
    {
      active:          viewMode === 'graph',
      selectedNode,
      onNodeClick:     setSelectedNode,
      onNodeHover:     setHoveredNode,
      searchQuery,
      filterCategory,
      onInsightsClick: (id) => { setHighlightedConceptId(id); setViewMode('insights') },
    }
  )

  // Mind map hooks (for Mind Map tab)
  const mindMap = useMindMap(
    svgRef,
    containerRef,
    graph,
    { active: viewMode === 'mindmap', onNodeClick: setSelectedNode, onNodeHover: setHoveredNode, selectedNodeId: selectedNode?.id }
  )

  const activeControls = viewMode === 'mindmap' ? mindMap : forceGraph

  const categoryCounts = useMemo(() => {
    if (!graph?.nodes) return {}
    return graph.nodes.reduce((acc, n) => {
      const cat = n.category || 'DEFAULT'
      acc[cat] = (acc[cat] || 0) + 1
      return acc
    }, {})
  }, [graph])

  const relatedEdges = useMemo(() => {
    if (!selectedNode || !graph?.edges) return []
    return graph.edges.filter(e => e.source === selectedNode.id || e.target === selectedNode.id)
  }, [selectedNode, graph])

  const conflicts = graph?.conflicts || []

  if (!graph) return null

  return (
    <div className="graph-view">
      {/* ── Sidebar ─────────────────────────────────────────── */}
      <aside className="graph-sidebar">

        {/* View toggle */}
        <div className="view-toggle-section">
          <button
            className={`view-btn ${viewMode==='mindmap'?'active':''}`}
            onClick={() => setViewMode('mindmap')}
          >
            <GitBranch size={13} /> Mind Map
          </button>
          <button
            className={`view-btn ${viewMode==='graph'?'active':''}`}
            onClick={() => setViewMode('graph')}
          >
            <Network size={13} /> Graph
          </button>
          <button
            className={`view-btn ${viewMode==='insights'?'active':''}`}
            onClick={() => setViewMode('insights')}
          >
            <Sparkles size={13} /> Insights
          </button>
        </div>

        {/* Mind map controls */}
        {viewMode === 'mindmap' && (
          <div className="sidebar-section">
            <div className="mm-controls">
              <button className="mm-ctrl-btn" onClick={mindMap.expandAll}>Expand All</button>
              <button className="mm-ctrl-btn" onClick={mindMap.collapseAll}>Collapse</button>
            </div>
            <div className="mm-hint font-mono">Click nodes to expand/collapse</div>
          </div>
        )}

        {/* Graph view: search + filter */}
        {viewMode === 'graph' && (
          <>
            <div className="sidebar-section">
              <div className="search-bar">
                <Search size={13} className="search-icon" />
                <input type="text" placeholder="Search concepts…" value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)} className="search-input font-mono" />
                {searchQuery && <button className="search-clear" onClick={()=>setSearchQuery('')}><X size={12}/></button>}
              </div>
            </div>
            <div className="sidebar-section">
              <div className="section-title"><Filter size={11}/><span>CATEGORIES</span></div>
              <div className="category-chips">
                <button className={`cat-chip ${!filterCategory?'active':''}`} onClick={()=>setFilterCategory(null)}>
                  All <span className="chip-count">{graph.nodes.length}</span>
                </button>
                {Object.entries(categoryCounts).map(([cat, count]) => (
                  <button key={cat}
                    className={`cat-chip ${filterCategory===cat?'active':''}`}
                    style={{'--cat-color': CATEGORY_COLORS[cat]||CATEGORY_COLORS.DEFAULT}}
                    onClick={()=>setFilterCategory(filterCategory===cat?null:cat)}>
                    <span className="chip-dot"/> {cat} <span className="chip-count">{count}</span>
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {/* Stats */}
        <div className="sidebar-section">
          <button className="section-title toggle-btn" onClick={()=>setShowStats(!showStats)}>
            <BarChart3 size={11}/><span>GRAPH STATS</span>
            <ChevronRight size={11} className={`chevron ${showStats?'open':''}`}/>
          </button>
          {showStats && (
            <div className="stats-grid animate-fade-in">
              <StatItem label="Nodes"     value={graph.nodes?.length??0}         color="var(--accent-cyan)"/>
              <StatItem label="Edges"     value={graph.edges?.length??0}         color="var(--accent-amber)"/>
              <StatItem label="Chunks"    value={graph.total_chunks_processed??0} color="var(--accent-green)"/>
              <StatItem label="Conflicts" value={conflicts.length}               color={conflicts.length>0?"var(--accent-red)":"var(--text-muted)"}/>
              {graph.stats && <>
                <StatItem label="Raw Concepts" value={graph.stats.concepts_before_merge??0}/>
                <StatItem label="Merged"       value={graph.stats.concepts_after_merge??0}/>
              </>}
            </div>
          )}
        </div>

        {/* Conflicts panel */}
        {conflicts.length > 0 && (
          <div className="sidebar-section conflicts-section">
            <button className="section-title toggle-btn conflict-title" onClick={()=>setShowConflicts(!showConflicts)}>
              <AlertTriangle size={11}/><span>CONFLICTS ({conflicts.length})</span>
              <ChevronRight size={11} className={`chevron ${showConflicts?'open':''}`}/>
            </button>
            {showConflicts && (
              <div className="conflicts-list animate-fade-in">
                {conflicts.map((c, i) => (
                  <div key={i} className="conflict-item font-mono">
                    <span className="conflict-badge">⚡</span>
                    <span className="conflict-desc">{c.description}</span>
                  </div>
                ))}
                <div className="conflict-note">Red dashed edges show contradictions in the source document.</div>
              </div>
            )}
          </div>
        )}

        {/* Summary */}
        {graph.global_summary && (
          <div className="sidebar-section">
            <button className="section-title toggle-btn" onClick={()=>setShowSummary(!showSummary)}>
              <BookOpen size={11}/><span>SUMMARY</span>
              <ChevronRight size={11} className={`chevron ${showSummary?'open':''}`}/>
            </button>
            {showSummary && <p className="summary-text animate-fade-in">{graph.global_summary}</p>}
          </div>
        )}

        {/* Selected node detail */}
        {selectedNode && (
          <div className="sidebar-section node-detail animate-slide-in">
            <div className="section-title">
              <Info size={11}/><span>NODE DETAIL</span>
              <button className="close-btn" onClick={()=>setSelectedNode(null)}><X size={11}/></button>
            </div>
            <div className="node-detail-body">
              <div className="node-detail-label" style={{color: CATEGORY_COLORS[selectedNode.category]||'#888'}}>
                {selectedNode.label}
              </div>
              <div className="node-detail-row">
                <span className="nd-key">Category</span>
                <span className="nd-val font-mono">{selectedNode.category||'CONCEPT'}</span>
              </div>
              <div className="node-detail-row">
                <span className="nd-key">Confidence</span>
                <ConfBar value={selectedNode.confidence}/>
              </div>
              <div className="node-detail-row">
                <span className="nd-key">Mentions</span>
                <span className="nd-val font-mono">{selectedNode.mention_count||1}</span>
              </div>
              {selectedNode.sentiment != null && (
                <div className="node-detail-row">
                  <span className="nd-key">Sentiment</span>
                  <SentimentBadge value={selectedNode.sentiment}/>
                </div>
              )}
              {/* Link to full definition in Insights */}
              {graph?.insights?.concept_descriptions?.[selectedNode.id] && (
                <button
                  className="insights-link-btn"
                  onClick={() => { setHighlightedConceptId(selectedNode.id); setViewMode('insights') }}
                >
                  <Sparkles size={11}/> View full definition in Insights
                </button>
              )}
              {relatedEdges.length > 0 && (
                <div className="node-relations">
                  <div className="nr-title">Relationships ({relatedEdges.length})</div>
                  <div className="nr-list">
                    {relatedEdges.slice(0,8).map((e,i)=>(
                      <div key={i} className="nr-item font-mono">
                        <span className="nr-type">{e.relation_type}</span>
                        <span className="nr-target">
                          {e.source===selectedNode.id ? `→ ${e.target}` : `← ${e.source}`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {/* Contextual description from RAG insights */}
              {graph?.insights?.concept_descriptions?.[selectedNode.id] && (
                <div className="node-context">
                  <div className="nr-title">In this document</div>
                  <p className="node-context-text">
                    {graph.insights.concept_descriptions[selectedNode.id]}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </aside>

      {/* ── Canvas / Insights Panel ─────────────────────────── */}
      <div className="graph-canvas-wrap" ref={containerRef}>
        {viewMode === 'insights' ? (
          <InsightsPanel highlightedId={highlightedConceptId} />
        ) : (
          <>
            <svg key={viewMode} ref={svgRef} className="graph-svg"/>

        {/* Hover tooltip */}
        {hoveredNode && !selectedNode && (
          <div className="node-tooltip">
            <span className="tooltip-label">{hoveredNode.label}</span>
            <span className="tooltip-cat font-mono">{hoveredNode.category}</span>
            {hoveredNode.confidence != null &&
              <span className="tooltip-conf font-mono">{Math.round(hoveredNode.confidence*100)}%</span>}
          </div>
        )}

        {/* View mode badge */}
        <div className="view-mode-badge font-mono">
          {viewMode === 'mindmap' ? '🌐 MIND MAP' : '⬡ FORCE GRAPH'}
        </div>

        {/* Zoom controls */}
        <div className="zoom-controls">
          <button className="zoom-btn" onClick={activeControls.zoomIn}   title="Zoom in"><ZoomIn size={15}/></button>
          <button className="zoom-btn" onClick={activeControls.zoomOut}  title="Zoom out"><ZoomOut size={15}/></button>
          <button className="zoom-btn" onClick={activeControls.resetZoom} title="Reset"><Maximize2 size={15}/></button>
        </div>

        {/* Legend (graph mode only) */}
        {viewMode === 'graph' && (
          <div className="graph-legend">
            {Object.entries(CATEGORY_COLORS).filter(([k])=>k!=='DEFAULT'&&k!=='CLUSTER').slice(0,6).map(([cat,color])=>(
              <div key={cat} className="legend-item">
                <div className="legend-dot" style={{background:color}}/>
                <span className="legend-label font-mono">{cat}</span>
              </div>
            ))}
          </div>
        )}

        {/* Mind map legend */}
        {viewMode === 'mindmap' && (
          <div className="mm-legend">
            <div className="mm-legend-item"><div className="mm-dot" style={{border:'2px solid #00e676'}}/><span>Positive sentiment</span></div>
            <div className="mm-legend-item"><div className="mm-dot" style={{border:'2px solid #ff1744'}}/><span>Negative sentiment</span></div>
            <div className="mm-legend-item"><div className="mm-dot" style={{background:'none',border:'2px dashed #ff1744'}}/><span>Conflict edge</span></div>
          </div>
        )}
          </>
        )}
      </div>
    </div>
  )
}

function StatItem({ label, value, color }) {
  return (
    <div className="stat-item">
      <span className="stat-value font-mono" style={color?{color}:{}}>{value}</span>
      <span className="stat-lbl">{label}</span>
    </div>
  )
}
function ConfBar({ value }) {
  const pct = Math.round((value||0)*100)
  return (
    <div className="conf-bar-wrap">
      <div className="conf-bar-track"><div className="conf-bar-fill" style={{width:`${pct}%`}}/></div>
      <span className="conf-pct font-mono">{pct}%</span>
    </div>
  )
}
function SentimentBadge({ value }) {
  const label = value>0.2?'positive':value<-0.2?'negative':'neutral'
  const color = value>0.2?'var(--accent-green)':value<-0.2?'var(--accent-red)':'var(--text-muted)'
  return <span className="sentiment-badge font-mono" style={{color,borderColor:color}}>{label} ({value?.toFixed(2)})</span>
}
