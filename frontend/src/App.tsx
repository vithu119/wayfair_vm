import React, { useEffect } from 'react'
import { Routes, Route, NavLink, useLocation, useNavigate } from 'react-router-dom'
import client from './api/client'
import { TemplatesPage } from './pages/TemplatesPage'
import { DataSourcesPage } from './pages/DataSourcesPage'
import { AsinsPage } from './pages/AsinsPage'
import { PreviewPage } from './pages/PreviewPage'
import { ValidationPage } from './pages/ValidationPage'
import { ExportPage } from './pages/ExportPage'
import { ContentConverterPage } from './pages/ContentConverterPage'
import { AdminPage } from './pages/AdminPage'
import { LoginPage } from './pages/LoginPage'
import { ProtectedRoute } from './components/ProtectedRoute'
import { useRunStore } from './store/runStore'
import { useAuthStore } from './store/authStore'

const NAV_ITEMS = [
  { path: '/templates', label: 'Templates', icon: '📋', step: 1 },
  { path: '/sources', label: 'Data Sources', icon: '📄', step: 2 },
  { path: '/asins', label: 'ASINs', icon: '🔑', step: 3 },
  { path: '/content', label: 'Content', icon: '✍️', step: 4 },
  { path: '/preview', label: 'Preview', icon: '👁', step: 5 },
  { path: '/validation', label: 'Validation', icon: '✅', step: 6 },
  { path: '/export', label: 'Export', icon: '📦', step: 7 },
]

function Sidebar() {
  return (
    <nav className="w-52 flex-shrink-0 bg-gray-50 border-r border-gray-200 flex flex-col">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          className={({ isActive }) =>
            `flex items-center gap-3 px-4 py-3 text-sm font-medium transition-colors ${
              isActive
                ? 'bg-blue-50 text-blue-700 border-r-2 border-blue-600'
                : 'text-gray-600 hover:bg-gray-100'
            }`
          }
        >
          <span>{item.icon}</span>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

function StatusBar() {
  const { uploadedTemplates, sourceFiles, asins, findings, exportFiles } = useRunStore()
  const blockingCount = findings.filter((f) => f.severity === 'blocking').length

  return (
    <div className="border-t border-gray-200 bg-gray-50 px-6 py-2 flex items-center gap-6 text-xs text-gray-500">
      <span>Templates: <strong>{uploadedTemplates.length}</strong></span>
      <span>Sources: <strong>{sourceFiles.length}</strong></span>
      <span>ASINs: <strong>{asins.length}</strong></span>
      {blockingCount > 0 && (
        <span className="text-red-600">Blocking issues: <strong>{blockingCount}</strong></span>
      )}
      {exportFiles.length > 0 && (
        <span className="text-green-600">Exports ready: <strong>{exportFiles.length}</strong></span>
      )}
    </div>
  )
}

function AppShell() {
  const { runId, setRunId, resetRun } = useRunStore()
  const { username, isAdmin, clearAuth } = useAuthStore()
  const navigate = useNavigate()

  useEffect(() => {
    if (!runId) return
    client.get(`/runs/${runId}`).catch((err) => {
      if (err?.response?.status === 404 || err?.response?.status === 403) {
        setRunId(null)
      }
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function handleLogout() {
    resetRun()
    clearAuth()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex flex-col h-screen">
      <header className="bg-blue-700 text-white px-6 py-3 flex items-center justify-between shadow-md flex-shrink-0">
        <h1 className="text-lg font-bold tracking-tight">Wayfair Template Auto-Fill</h1>
        <div className="flex items-center gap-4 text-sm">
          <span className="opacity-75">{username}</span>
          {isAdmin && (
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                `px-3 py-1 rounded text-xs font-medium transition-colors ${
                  isActive ? 'bg-blue-900 text-white' : 'bg-blue-800 hover:bg-blue-900 text-white'
                }`
              }
            >
              Admin
            </NavLink>
          )}
          <button
            onClick={handleLogout}
            className="bg-blue-800 hover:bg-blue-900 px-3 py-1 rounded text-xs font-medium transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/" element={<TemplatesPage />} />
            <Route path="/templates" element={<TemplatesPage />} />
            <Route path="/sources" element={<DataSourcesPage />} />
            <Route path="/asins" element={<AsinsPage />} />
            <Route path="/preview" element={<PreviewPage />} />
            <Route path="/validation" element={<ValidationPage />} />
            <Route path="/export" element={<ExportPage />} />
            <Route path="/content" element={<ContentConverterPage />} />
            {isAdmin && <Route path="/admin" element={<AdminPage />} />}
          </Routes>
        </main>
      </div>

      <StatusBar />
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}
