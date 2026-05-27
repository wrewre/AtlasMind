import React, { useEffect } from 'react'
import { Toaster } from 'react-hot-toast'
import useStore from './store/useStore'
import UploadView from './components/UploadView'
import ProcessingView from './components/ProcessingView'
import GraphView from './components/GraphView'
import Header from './components/Header'
import AuthModal from './components/AuthModal'
import HistoryDrawer from './components/HistoryDrawer'
import './App.css'

export default function App() {
  const { activeView, isAuthenticated, initAuth, isHistoryOpen } = useStore()

  // Restore auth state from localStorage on mount
  useEffect(() => {
    initAuth()
  }, [])

  return (
    <div className="app-shell">
      <Header />
      <main className="app-main">
        {activeView === 'upload'     && <UploadView />}
        {activeView === 'processing' && <ProcessingView />}
        {activeView === 'graph'      && <GraphView />}
      </main>

      {/* Auth gate — shown when not authenticated */}
      {!isAuthenticated && <AuthModal />}

      {/* History drawer — slide-out panel */}
      <HistoryDrawer />

      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: 'var(--bg-elevated)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-default)',
            fontFamily: 'var(--font-display)',
            fontSize: '13px',
          },
          success: { iconTheme: { primary: 'var(--accent-green)', secondary: 'var(--bg-base)' } },
          error:   { iconTheme: { primary: 'var(--accent-red)',   secondary: 'var(--bg-base)' } },
        }}
      />
    </div>
  )
}
