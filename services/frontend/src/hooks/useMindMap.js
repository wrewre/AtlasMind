/**
 * useMindMap — D3 Radial Tree (keyword mind map only, no descriptions)
 * Keywords-only view — descriptions belong in the Graph tab.
 */
import { useEffect, useCallback, useRef } from 'react'
import * as d3 from 'd3'

const CATEGORY_COLORS = {
  ENTITY:'#00e5ff', TECHNOLOGY:'#7c3aed', PROCESS:'#ffb300',
  CONCEPT:'#00e676', PERSON:'#ff6090', ORGANIZATION:'#ff9800',
  LOCATION:'#4fc3f7', EVENT:'#f06292', CLUSTER:'#606080',
  ROOT:'#f0f0f8', DEFAULT:'#8888aa',
}

export default function useMindMap(svgRef, containerRef, graph, options = {}) {
  const { active, onNodeClick, onNodeHover, selectedNodeId } = options
  const collapsedRef = useRef(new Set())
  const activeRef    = useRef(active)
  useEffect(() => { activeRef.current = active }, [active])

  const render = useCallback(() => {
    // IMPORTANT: return BEFORE touching the SVG when inactive
    if (!active) return
    if (!svgRef.current || !containerRef.current || !graph?.tree) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    const W = containerRef.current.clientWidth  || 900
    const H = containerRef.current.clientHeight || 650
    svg.attr('width', W).attr('height', H)

    const g    = svg.append('g')
    const zoom = d3.zoom().scaleExtent([0.08, 4])
      .on('zoom', e => g.attr('transform', e.transform))
    svg.call(zoom)

    const collapsed = collapsedRef.current

    function cloneNode(n) {
      const clone = { ...n }
      if (collapsed.has(n.id)) { clone.children = []; clone._collapsed = true }
      else clone.children = (n.children || []).map(cloneNode)
      return clone
    }

    const root      = d3.hierarchy(cloneNode(graph.tree))
    const nodeCount = root.descendants().length

    // Generous radius that scales properly with large graphs — no artificial cap
    const radius = Math.max(380, Math.min(W, H) * 0.44 * Math.max(0.9, nodeCount / 5.5))

    const tree = d3.tree()
      .size([2 * Math.PI, radius])
      // Flat angular separation — no depth penalty that crushes nodes together
      .separation((a, b) => a.parent === b.parent ? 2.8 : 5.2)
    tree(root)

    // Auto-fit: scale so the full radial tree is visible without scrolling
    const fitScale = Math.max(0.1, Math.min(0.88, (Math.min(W, H) - 100) / (2 * radius + 80)))
    svg.call(zoom.transform, d3.zoomIdentity.translate(W / 2, H / 2).scale(fitScale))

    const conflictPairs = new Set(
      (graph.conflicts || []).map(c => `${c.edge_a.source}-${c.edge_a.target}`)
    )

    // Links
    g.append('g').attr('fill', 'none').selectAll('path')
      .data(root.links()).join('path')
      .attr('d', d3.linkRadial().angle(d => d.x).radius(d => d.y))
      .attr('stroke', d => conflictPairs.has(`${d.source.data.id}-${d.target.data.id}`) ? '#ff1744' : 'rgba(150,150,200,0.28)')
      .attr('stroke-width', d => Math.max(1, 3 - d.target.depth * 0.7))
      .attr('stroke-dasharray', d => conflictPairs.has(`${d.source.data.id}-${d.target.data.id}`) ? '4,3' : 'none')
      .attr('opacity', 0).transition().duration(700).delay((_, i) => i * 10).attr('opacity', 1)

    // Nodes
    const nodeG = g.append('g')
    const node  = nodeG.selectAll('g').data(root.descendants()).join('g')
      .attr('transform', d => `rotate(${d.x * 180 / Math.PI - 90}) translate(${d.y},0)`)
      .attr('cursor', 'pointer')

    const nodeR     = d => d.depth === 0 ? 22 : d.depth === 1 ? Math.max(11, 16 + (d.data.mention_count||1)) : Math.max(6, 13 - d.depth * 1.5)
    const nodeColor = d => CATEGORY_COLORS[d.data.category] || CATEGORY_COLORS.DEFAULT

    // Selection ring
    node.append('circle').attr('r', d => nodeR(d) + 5).attr('fill', 'none')
      .attr('stroke', d => nodeColor(d)).attr('stroke-width', 1.5)
      .attr('stroke-opacity', d => d.data.id === selectedNodeId ? 0.75 : 0)

    // Sentiment ring
    node.append('circle').attr('r', d => nodeR(d) + 3).attr('fill', 'none')
      .attr('stroke', d => { const s = d.data.sentiment; return s > 0.2 ? '#00e676' : s < -0.2 ? '#ff1744' : 'transparent' })
      .attr('stroke-width', 2).attr('stroke-dasharray', '3 2').attr('stroke-opacity', 0.5)

    // Main circle
    node.append('circle').attr('r', d => nodeR(d))
      .attr('fill', d => d.depth === 0 ? 'rgba(240,240,248,0.1)' : `${nodeColor(d)}22`)
      .attr('stroke', d => nodeColor(d)).attr('stroke-width', d => d.depth === 0 ? 2.5 : 1.5)
      .attr('opacity', 0).transition().duration(500).delay(d => d.depth * 70).attr('opacity', 1)

    // Collapse indicator
    node.filter(d => d.data._collapsed).append('text')
      .attr('text-anchor', 'middle').attr('dy', '0.35em')
      .attr('font-size', 10).attr('fill', '#ffb300').text('+')

    // Confidence % badge (depth 1-2 only)
    node.filter(d => d.depth > 0 && d.depth <= 2 && !d.data._collapsed).append('text')
      .attr('text-anchor', 'middle').attr('dy', '0.35em')
      .attr('font-size', 7).attr('font-family', "'Space Mono',monospace")
      .attr('fill', d => nodeColor(d)).attr('opacity', 0.7)
      .text(d => `${Math.round((d.data.confidence || 0) * 100)}%`)

    // Labels — keywords only, no description boxes
    node.append('text')
      .attr('dy', '0.31em')
      .attr('x', d => { const r = nodeR(d) + 14; return d.x < Math.PI === !d.children ? r : -r })
      .attr('text-anchor', d => d.x < Math.PI === !d.children ? 'start' : 'end')
      .attr('transform', d => d.x >= Math.PI ? 'rotate(180)' : null)
      .attr('fill', d => d.depth === 0 ? '#fff' : '#eeeeff')
      .attr('font-size', d => d.depth === 0 ? 15 : d.depth === 1 ? 13 : 11)
      .attr('font-weight', d => d.depth <= 1 ? 700 : 500)
      .attr('font-family', "'Syne', sans-serif")
      .attr('paint-order', 'stroke').attr('stroke', 'rgba(6,6,14,0.85)').attr('stroke-width', 4).attr('stroke-linejoin', 'round')
      .attr('opacity', 0)
      .text(d => { const lbl = d.data.label || d.data.id; const m = d.depth === 0 ? 30 : d.depth === 1 ? 22 : 18; return lbl.length > m ? lbl.slice(0, m-1) + '…' : lbl })
      .transition().duration(500).delay(d => d.depth * 90).attr('opacity', 1)

    node.on('click', (event, d) => {
      event.stopPropagation()
      if (d.depth === 0) return
      const hasKids = countChildren(graph.tree, d.data.id) > 0
      if (hasKids) { collapsed.has(d.data.id) ? collapsed.delete(d.data.id) : collapsed.add(d.data.id); render() }
      if (onNodeClick) onNodeClick(d.data)
    })
    .on('mouseenter', (_, d) => { if (onNodeHover && d.depth > 0) onNodeHover(d.data) })
    .on('mouseleave', ()     => { if (onNodeHover) onNodeHover(null) })
    svg.on('click', () => { if (onNodeClick) onNodeClick(null) })

  }, [graph, active, selectedNodeId, onNodeClick, onNodeHover])

  useEffect(() => { render() }, [render])

  function countChildren(tree, id) {
    if (tree.id === id) return (tree.children||[]).length
    for (const c of tree.children||[]) { const f = countChildren(c, id); if (f >= 0) return f }
    return -1
  }

  const zoomIn    = useCallback(() => { if(!svgRef.current)return; d3.select(svgRef.current).transition().call(d3.zoom().scaleBy,1.3) },[])
  const zoomOut   = useCallback(() => { if(!svgRef.current)return; d3.select(svgRef.current).transition().call(d3.zoom().scaleBy,0.77) },[])
  const resetZoom = useCallback(() => {
    if(!svgRef.current||!containerRef.current)return
    const W=containerRef.current.clientWidth, H=containerRef.current.clientHeight
    d3.select(svgRef.current).transition().duration(400)
      .call(d3.zoom().transform, d3.zoomIdentity.translate(W/2,H/2).scale(0.85))
  },[])
  const expandAll   = useCallback(() => { collapsedRef.current.clear(); render() },[render])
  const collapseAll = useCallback(() => {
    if (!graph?.tree) return
    const ids = new Set()
    function collect(n) { if(n.children?.length){ ids.add(n.id); n.children.forEach(collect) } }
    graph.tree.children?.forEach(collect)
    collapsedRef.current = ids; render()
  },[graph, render])

  return { zoomIn, zoomOut, resetZoom, expandAll, collapseAll }
}
