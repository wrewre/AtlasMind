import React, { useState } from 'react'
import { Download, FileJson, Image, FileCode2 } from 'lucide-react'
import useStore from '../store/useStore'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'
import './ExportPanel.css'

export default function ExportPanel() {
  const [isOpen, setIsOpen] = useState(false)
  const { graph, fileName } = useStore()
  const baseName = fileName ? fileName.split('.')[0] : 'mindmap'

  const handleExportJSON = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(graph, null, 2))
    const a = document.createElement('a')
    a.href = dataStr
    a.download = `${baseName}_graph.json`
    a.click()
    setIsOpen(false)
  }

  const handleExportImage = async () => {
    const graphElement = document.querySelector('.graph-container svg')
    if (!graphElement) return

    // Create a wrapper div to render the SVG properly
    const wrapper = document.createElement('div')
    wrapper.style.position = 'absolute'
    wrapper.style.left = '-9999px'
    wrapper.style.background = '#0a0a0f' // Match app background
    
    // Clone SVG to not mess with the live DOM
    const clone = graphElement.cloneNode(true)
    // Ensure styles are inline for canvas rendering
    clone.style.width = '1920px'
    clone.style.height = '1080px'
    wrapper.appendChild(clone)
    document.body.appendChild(wrapper)

    try {
      const canvas = await html2canvas(wrapper, {
        backgroundColor: '#0a0a0f',
        scale: 2, // High resolution
        logging: false,
      })
      const link = document.createElement('a')
      link.download = `${baseName}_mindmap.png`
      link.href = canvas.toDataURL('image/png')
      link.click()
    } finally {
      document.body.removeChild(wrapper)
      setIsOpen(false)
    }
  }

  const handleExportPDF = async () => {
    const graphElement = document.querySelector('.graph-container svg')
    if (!graphElement) return

    const wrapper = document.createElement('div')
    wrapper.style.position = 'absolute'
    wrapper.style.left = '-9999px'
    wrapper.style.background = '#ffffff' // White bg for PDF usually better
    
    const clone = graphElement.cloneNode(true)
    clone.style.width = '1600px'
    clone.style.height = '1200px'
    
    // Invert text colors for white background
    const texts = clone.querySelectorAll('text')
    texts.forEach(t => t.style.fill = '#000000')

    wrapper.appendChild(clone)
    document.body.appendChild(wrapper)

    try {
      const canvas = await html2canvas(wrapper, {
        backgroundColor: '#ffffff',
        scale: 2,
        logging: false,
      })
      
      const imgData = canvas.toDataURL('image/png')
      const pdf = new jsPDF({
        orientation: 'landscape',
        unit: 'px',
        format: [1600, 1200]
      })
      
      pdf.addImage(imgData, 'PNG', 0, 0, 1600, 1200)
      pdf.save(`${baseName}_mindmap.pdf`)
    } finally {
      document.body.removeChild(wrapper)
      setIsOpen(false)
    }
  }

  return (
    <div className="export-panel">
      <button 
        className="header-icon-btn export-trigger" 
        onClick={() => setIsOpen(!isOpen)}
        title="Export options"
      >
        <Download size={15} />
      </button>

      {isOpen && (
        <div className="export-dropdown animate-fade-in">
          <div className="export-header font-mono">EXPORT AS</div>
          
          <button className="export-opt" onClick={handleExportImage}>
            <Image size={14} className="export-icon" />
            <div className="export-text">
              <span>High-Res PNG</span>
              <span className="export-sub">Ideal for sharing</span>
            </div>
          </button>
          
          <button className="export-opt" onClick={handleExportPDF}>
            <FileCode2 size={14} className="export-icon" />
            <div className="export-text">
              <span>PDF Document</span>
              <span className="export-sub">Printable vector</span>
            </div>
          </button>

          <div className="export-divider" />
          
          <button className="export-opt" onClick={handleExportJSON}>
            <FileJson size={14} className="export-icon json-icon" />
            <div className="export-text">
              <span>Raw JSON</span>
              <span className="export-sub">Full graph data</span>
            </div>
          </button>
        </div>
      )}

      {/* Click outside to close overlay */}
      {isOpen && (
        <div className="export-overlay" onClick={() => setIsOpen(false)} />
      )}
    </div>
  )
}
