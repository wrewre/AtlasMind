/**
 * useForceGraph — Horizontal Hierarchy Tree (Graph View)
 *
 * - Shows FULL concept descriptions (not keywords) — NotebookLM-style
 * - Clicking a leaf node navigates to the matching card in Document Insights
 * - Auto-fits the entire tree into view on load
 * - Increased ROW_H / COL_W for better spacing
 */
import { useEffect, useCallback, useRef } from 'react'
import * as d3 from 'd3'

const CAT_BORDER = {
  ENTITY:'#00e5ff', TECHNOLOGY:'#7c3aed', PROCESS:'#ffb300',
  CONCEPT:'#00e676', PERSON:'#ff6090', ORGANIZATION:'#ff9800',
  LOCATION:'#4fc3f7', EVENT:'#f06292', CLUSTER:'#606080', DEFAULT:'#5566aa',
}

// Split a description into individual sentences — show ALL of them (no hard cap)
function splitDesc(text) {
  if (!text) return []
  return text
    .replace(/([.!?])\s+/g, '$1|||')
    .split('|||')
    .map(s => s.trim())
    .filter(s => s.length > 6)
}

function buildTree(node, insights, collapsed) {
  if (!node) return null
  const clone = {
    id: node.id, label: node.label, category: node.category,
    confidence: node.confidence, mention_count: node.mention_count,
  }
  if (collapsed.has(node.id)) {
    clone._collapsed = true
    clone.children = []
  } else if (node.children?.length > 0) {
    clone.children = node.children.map(c => buildTree(c, insights, collapsed)).filter(Boolean)
  } else {
    const desc = insights?.concept_descriptions?.[node.id]
    const sentences = splitDesc(desc)
    clone.children = sentences.map((b, i) => ({
      id: `${node.id}__leaf__${i}`,
      label: b,
      isLeaf: true,
      parentConceptId: node.id,
      // Mark long descriptions so UI can show a "view full" affordance
      isLong: desc && desc.length > 200,
      children: [],
    }))
  }
  return clone
}

export default function useForceGraph(svgRef, containerRef, graph, options = {}) {
  const selectedNodeRef    = useRef(options.selectedNode)
  const onNodeClickRef     = useRef(options.onNodeClick)
  const onNodeHoverRef     = useRef(options.onNodeHover)
  const onInsightsClickRef = useRef(options.onInsightsClick)
  const searchQueryRef     = useRef(options.searchQuery)
  const activeRef          = useRef(options.active)

  useEffect(() => { selectedNodeRef.current    = options.selectedNode },    [options.selectedNode])
  useEffect(() => { onNodeClickRef.current     = options.onNodeClick },     [options.onNodeClick])
  useEffect(() => { onNodeHoverRef.current     = options.onNodeHover },     [options.onNodeHover])
  useEffect(() => { onInsightsClickRef.current = options.onInsightsClick }, [options.onInsightsClick])
  useEffect(() => { searchQueryRef.current     = options.searchQuery },     [options.searchQuery])
  useEffect(() => { activeRef.current          = options.active },          [options.active])

  const collapsedRef  = useRef(new Set())
  const zoomRef       = useRef(null)
  const positionsRef  = useRef({})
  const graphRef      = useRef(graph)
  useEffect(() => { graphRef.current = graph }, [graph])

  const render = useCallback(() => {
    if (!options.active) return
    if (!svgRef.current || !containerRef.current || !graphRef.current?.tree) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    const W = containerRef.current.clientWidth  || 900
    const H = containerRef.current.clientHeight || 650
    svg.attr('width', W).attr('height', H)

    const g    = svg.append('g')
    const zoom = d3.zoom().scaleExtent([0.03, 3])
      .on('zoom', e => g.attr('transform', e.transform))
    zoomRef.current = zoom
    svg.call(zoom)

    const insights  = graphRef.current.insights
    const collapsed = collapsedRef.current

    const treeData = buildTree(graphRef.current.tree, insights, collapsed)
    if (!treeData) return

    const root = d3.hierarchy(treeData, d => d.children?.length ? d.children : null)

    // Generous spacing so descriptions never look cramped
    const ROW_H = 76
    const COL_W = 390
    const tree  = d3.tree().nodeSize([ROW_H, COL_W])
    tree(root)

    // Store positions for search navigation
    positionsRef.current = {}
    root.descendants().forEach(d => {
      if (!d.data.isLeaf) positionsRef.current[d.data.id] = { x: d.y, y: d.x }
    })

    // ── Auto-fit: scale to show the ENTIRE tree at once ──────────────────
    let minSvgX = Infinity, maxSvgX = -Infinity
    let minSvgY = Infinity, maxSvgY = -Infinity
    root.descendants().forEach(d => {
      // In linkHorizontal layout: SVG x = d.y (column), SVG y = d.x (row)
      const nodeW = d.data.isLeaf ? 380 : d.depth === 0 ? 260 : 230
      minSvgX = Math.min(minSvgX, d.y)
      maxSvgX = Math.max(maxSvgX, d.y + nodeW)
      minSvgY = Math.min(minSvgY, d.x - ROW_H / 2)
      maxSvgY = Math.max(maxSvgY, d.x + ROW_H / 2)
    })
    const treeW = maxSvgX - minSvgX
    const treeH = maxSvgY - minSvgY
    const fitScale = Math.max(0.04, Math.min(0.9,
      Math.min((W - 140) / treeW, (H - 80) / treeH)
    ))
    const tx = -minSvgX * fitScale + 60
    const ty = H / 2 - ((minSvgY + maxSvgY) / 2) * fitScale
    svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(fitScale))

    // ── Links ─────────────────────────────────────────────────────────────
    g.append('g').attr('fill', 'none').selectAll('path')
      .data(root.links()).join('path')
      .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x))
      .attr('stroke', d => d.target.data.isLeaf
        ? 'rgba(70,150,100,0.35)' : 'rgba(110,110,200,0.4)')
      .attr('stroke-width', d => d.target.data.isLeaf ? 1 : 1.5)
      .attr('opacity', 0)
      .transition().duration(500).delay((_, i) => i * 6).attr('opacity', 1)

    // ── Nodes ─────────────────────────────────────────────────────────────
    const nodeG = g.append('g')
    const node  = nodeG.selectAll('g').data(root.descendants()).join('g')
      .attr('transform', d => `translate(${d.y},${d.x})`)
      .attr('cursor', 'pointer')

    const boxW = d => {
      if (d.depth === 0)  return Math.min(260, (d.data.label||'').length * 9 + 36)
      if (d.data.isLeaf)  return Math.min(420, (d.data.label||'').length * 7.2 + 30)
      return Math.min(230, (d.data.label||'').length * 8.5 + 30)
    }
    const boxH = d => d.data.isLeaf ? 32 : d.depth === 0 ? 42 : 36

    // Box
    node.append('rect')
      .attr('class', d => d.data.isLeaf ? 'tree-leaf-box' : 'tree-concept-box')
      .attr('data-id', d => d.data.id)
      .attr('y', d => -boxH(d) / 2)
      .attr('width', d => boxW(d)).attr('height', d => boxH(d))
      .attr('rx', 7)
      .attr('fill', d => d.data.isLeaf ? 'rgba(10,32,20,0.92)' : d.depth === 0 ? 'rgba(22,22,52,0.96)' : 'rgba(16,16,38,0.92)')
      .attr('stroke', d => d.data.isLeaf ? 'rgba(50,130,90,0.72)' : (CAT_BORDER[d.data.category] || CAT_BORDER.DEFAULT))
      .attr('stroke-width', d => d.depth === 0 ? 2 : 1)
      .attr('opacity', 0)
      .transition().duration(380).delay(d => d.depth * 40).attr('opacity', 1)

    // "→ Insights" badge for long definitions
    node.filter(d => d.data.isLeaf && d.data.isLong).append('text')
      .attr('x', d => boxW(d) - 8).attr('y', 5)
      .attr('text-anchor', 'end')
      .attr('font-size', 9).attr('fill', 'rgba(0,229,255,0.65)').attr('font-family', "'Space Mono',monospace")
      .text('→ full')

    // Expand/collapse arrows — OWN click handler, never navigates to Insights
    const arrowCollapsed = node.filter(d => !d.data.isLeaf && d.data._collapsed).append('text')
      .attr('class', 'collapse-arrow')
      .attr('x', d => boxW(d) - 16).attr('y', 6)
      .attr('font-size', 15).attr('fill', '#ffb300').attr('font-family', 'monospace')
      .attr('cursor', 'pointer').text('›')
    const arrowExpanded = node.filter(d => !d.data.isLeaf && !d.data._collapsed && d.children?.length > 0).append('text')
      .attr('class', 'collapse-arrow')
      .attr('x', d => boxW(d) - 16).attr('y', 6)
      .attr('font-size', 13).attr('fill', 'rgba(130,130,200,0.45)').attr('font-family', 'monospace')
      .attr('cursor', 'pointer').text('‹')

    // Arrow click: ONLY toggle collapse, stop propagation so box click doesn't fire
    function handleArrowClick(event, d) {
      event.stopPropagation()
      if (d.depth === 0) return
      collapsedRef.current.has(d.data.id)
        ? collapsedRef.current.delete(d.data.id)
        : collapsedRef.current.add(d.data.id)
      render()
    }
    arrowCollapsed.on('click', handleArrowClick)
    arrowExpanded.on('click', handleArrowClick)

    // Label text
    node.append('text')
      .attr('x', d => d.depth === 0 ? 14 : 10).attr('y', 5)
      .attr('fill', d => d.data.isLeaf ? 'rgba(155,225,180,0.94)' : d.depth === 0 ? '#ffffff' : '#dde0ff')
      .attr('font-size', d => d.depth === 0 ? 14 : d.data.isLeaf ? 11.5 : 12.5)
      .attr('font-weight', d => (d.depth <= 1) ? 600 : 400)
      .attr('font-family', d => d.data.isLeaf ? "'Inter',sans-serif" : "'Syne',sans-serif")
      .attr('opacity', 0)
      .text(d => {
        // Show more text in graph leaves — full descriptions visible here
        const max = d.data.isLeaf ? 72 : d.depth === 0 ? 30 : 26
        const lbl = d.data.label || ''
        return lbl.length > max ? lbl.slice(0, max - 1) + '…' : lbl
      })
      .transition().duration(380).delay(d => d.depth * 40 + 60).attr('opacity', 1)

    // ── Interactions ──────────────────────────────────────────────────────
    node.on('click', function(event, d) {
      event.stopPropagation()
      // Arrow clicked → arrow's own handler manages collapse; ignore here
      if (event.target.classList.contains('collapse-arrow')) return
      const currentGraph = graphRef.current
      const onInsights   = onInsightsClickRef.current
      const onNodeClick  = onNodeClickRef.current

      if (d.data.isLeaf) {
        // Leaf click → always navigate to Document Insights for the full definition
        const parentId   = d.data.parentConceptId
        const hasInsights = !!(currentGraph?.insights?.concept_descriptions?.[parentId])
        if (hasInsights && onInsights) {
          d3.select(this).select('rect')
            .transition().duration(100).attr('stroke', '#ffffff').attr('stroke-width', 3)
            .transition().duration(120).attr('stroke', '#00ff88').attr('stroke-width', 2.5)
            .transition().duration(120).attr('stroke', '#ffffff').attr('stroke-width', 3)
            .transition().duration(120).attr('stroke', '#00ff88').attr('stroke-width', 2)
          setTimeout(() => onInsights(parentId), 480)
        }
        return
      }

      // Concept node body click → navigate to Insights only (collapse handled by arrow)
      const hasDesc = !!(currentGraph?.insights?.concept_descriptions?.[d.data.id])

      if (onNodeClick) onNodeClick(d.data)
      if (hasDesc && onInsights) {
        d3.select(this).select('rect')
          .transition().duration(150).attr('stroke', '#ffffff').attr('stroke-width', 2.5)
          .transition().duration(200).attr('stroke', CAT_BORDER[d.data.category] || CAT_BORDER.DEFAULT).attr('stroke-width', 1.5)
        setTimeout(() => onInsights(d.data.id), 350)
      }
    })
    .on('mouseenter', (_, d) => { if (!d.data.isLeaf && onNodeHoverRef.current) onNodeHoverRef.current(d.data) })
    .on('mouseleave', ()     => { if (onNodeHoverRef.current) onNodeHoverRef.current(null) })

    svg.on('click', () => { if (onNodeClickRef.current) onNodeClickRef.current(null) })

  }, [graph, options.active])

  useEffect(() => { render() }, [render])

  // ── Selected node highlight — no full redraw ─────────────────────────
  useEffect(() => {
    if (!svgRef.current) return
    d3.select(svgRef.current).selectAll('.tree-concept-box').each(function(d) {
      if (!d) return
      const sel = options.selectedNode?.id === d.data?.id
      d3.select(this)
        .transition().duration(180)
        .attr('stroke', sel ? '#ffffff' : (CAT_BORDER[d.data?.category] || CAT_BORDER.DEFAULT))
        .attr('stroke-width', sel ? 2.5 : d.depth === 0 ? 2 : 1)
    })
  }, [options.selectedNode])

  // ── Search: navigate to matching node ───────────────────────────────
  useEffect(() => {
    if (!options.searchQuery?.trim() || !svgRef.current || !containerRef.current) return

    const doSearch = () => {
      if (!zoomRef.current) return
      const q = options.searchQuery.toLowerCase().trim()

      const match = graphRef.current?.nodes?.find(n =>
        (n.label || '').toLowerCase().includes(q) ||
        (n.id    || '').toLowerCase().includes(q)
      )
      if (!match) return

      // Expand collapsed ancestors so the node is visible
      if (collapsedRef.current.has(match.id)) {
        collapsedRef.current.delete(match.id)
        render()
      }

      let pos = positionsRef.current[match.id]
      if (!pos) {
        const key = Object.keys(positionsRef.current).find(k => k.toLowerCase().includes(q))
        if (key) pos = positionsRef.current[key]
      }
      if (!pos) return

      const W = containerRef.current.clientWidth  || 900
      const H = containerRef.current.clientHeight || 650
      const s = 1.6

      d3.select(svgRef.current)
        .transition().duration(650).ease(d3.easeCubicInOut)
        .call(zoomRef.current.transform,
          d3.zoomIdentity.translate(W / 2 - pos.x * s, H / 2 - pos.y * s).scale(s))

      // Pulse the matched box
      d3.select(svgRef.current).selectAll('.tree-concept-box').each(function(d) {
        if (d?.data?.id !== match.id) return
        const col = CAT_BORDER[d.data.category] || CAT_BORDER.DEFAULT
        d3.select(this)
          .transition().duration(160).attr('stroke', '#fff').attr('stroke-width', 3)
          .transition().duration(220).attr('stroke', col).attr('stroke-width', 1.5)
          .transition().duration(160).attr('stroke', '#fff').attr('stroke-width', 3)
          .transition().duration(220).attr('stroke', col).attr('stroke-width', 1.5)
      })
    }

    const t = setTimeout(doSearch, 150)
    return () => clearTimeout(t)
  }, [options.searchQuery])

  const zoomIn    = useCallback(() => { if(!svgRef.current)return; d3.select(svgRef.current).transition().call(d3.zoom().scaleBy,1.4) },[])
  const zoomOut   = useCallback(() => { if(!svgRef.current)return; d3.select(svgRef.current).transition().call(d3.zoom().scaleBy,0.7) },[])
  const resetZoom = useCallback(() => {
    if(!svgRef.current||!containerRef.current)return
    const H=containerRef.current.clientHeight||650
    d3.select(svgRef.current).transition().duration(400)
      .call(d3.zoom().transform, d3.zoomIdentity.translate(80,H/2).scale(0.85))
  },[])

  return { zoomIn, zoomOut, resetZoom }
}
