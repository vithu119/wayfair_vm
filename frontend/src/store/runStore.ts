import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { TemplateEntry, SourceFile, ResolvedProduct, ValidationFinding, ExportFile, PreviewRow, AsinValidationItem } from '../types'
import type { ConvertResponse, BatchResponse } from '../api/content'

interface RunStore {
  runId: string | null
  uploadedTemplates: TemplateEntry[]
  sourceFiles: SourceFile[]
  asins: string[]
  asinItems: AsinValidationItem[]
  resolvedProducts: ResolvedProduct[]
  manualEdits: Record<string, string>
  findings: ValidationFinding[]
  exportFiles: ExportFile[]
  sessionApprovedTemplates: Set<string>
  previewRows: PreviewRow[]
  previewHeaders: string[]
  singleResult: ConvertResponse | null
  batchResponse: BatchResponse | null
  batchAsinText: string
  singleInputs: { title: string; bulletsText: string; description: string; variantsText: string; groupRefId: string }

  setRunId: (id: string | null) => void
  setTemplates: (templates: TemplateEntry[]) => void
  addTemplate: (template: TemplateEntry) => void
  setSources: (sources: SourceFile[]) => void
  addSource: (source: SourceFile) => void
  removeTemplate: (templateId: string) => void
  removeSource: (sourceId: string) => void
  setAsins: (asins: string[]) => void
  setAsinItems: (items: AsinValidationItem[]) => void
  setProducts: (products: ResolvedProduct[]) => void
  setManualEdit: (key: string, value: string) => void
  setFindings: (findings: ValidationFinding[]) => void
  setExports: (files: ExportFile[]) => void
  approveTemplate: (templateId: string) => void
  revokeApproval: (templateId: string) => void
  setPreviewRows: (rows: PreviewRow[], headers: string[]) => void
  setSingleResult: (result: ConvertResponse | null) => void
  setBatchResponse: (response: BatchResponse | null) => void
  setBatchAsinText: (text: string) => void
  autoRunBatch: boolean
  setAutoRunBatch: (v: boolean) => void
  setSingleInputs: (inputs: Partial<RunStore['singleInputs']>) => void
  resetRun: () => void
  resetDownstream: () => void
}

export const useRunStore = create<RunStore>()(
  persist(
    (set, get) => ({
      runId: null,
      uploadedTemplates: [],
      sourceFiles: [],
      asins: [],
      asinItems: [],
      resolvedProducts: [],
      manualEdits: {},
      findings: [],
      exportFiles: [],
      sessionApprovedTemplates: new Set(),
      previewRows: [],
      previewHeaders: [],
      singleResult: null,
      batchResponse: null,
      batchAsinText: '',
      autoRunBatch: false,
      singleInputs: { title: '', bulletsText: '', description: '', variantsText: '', groupRefId: '' },

      setRunId: (id) => set({ runId: id }),
      setTemplates: (templates) => set({ uploadedTemplates: templates }),
      addTemplate: (template) =>
        set((s) => ({
          uploadedTemplates: [
            ...s.uploadedTemplates.filter((t) => t.template_id !== template.template_id),
            template,
          ],
        })),
      setSources: (sources) => set({ sourceFiles: sources }),
      addSource: (source) =>
        set((s) => ({
          sourceFiles: [
            ...s.sourceFiles.filter((f) => f.source_id !== source.source_id),
            source,
          ],
        })),
      removeTemplate: (templateId) =>
        set((s) => ({ uploadedTemplates: s.uploadedTemplates.filter((t) => t.template_id !== templateId) })),
      removeSource: (sourceId) =>
        set((s) => ({ sourceFiles: s.sourceFiles.filter((f) => f.source_id !== sourceId) })),
      setAsins: (asins) => set({ asins }),
      setAsinItems: (items) => set({ asinItems: items }),
      setProducts: (products) => set({ resolvedProducts: products }),
      setManualEdit: (key, value) =>
        set((s) => ({ manualEdits: { ...s.manualEdits, [key]: value } })),
      setFindings: (findings) => set({ findings }),
      setExports: (files) => set({ exportFiles: files }),
      setPreviewRows: (rows, headers) => set({ previewRows: rows, previewHeaders: headers }),
      setSingleResult: (result) => set({ singleResult: result }),
      setBatchResponse: (response) => set({ batchResponse: response }),
      setBatchAsinText: (text) => set({ batchAsinText: text }),
      setAutoRunBatch: (v) => set({ autoRunBatch: v }),
      setSingleInputs: (inputs) => set((s) => ({ singleInputs: { ...s.singleInputs, ...inputs } })),
      approveTemplate: (templateId) =>
        set((s) => ({
          sessionApprovedTemplates: new Set([...s.sessionApprovedTemplates, templateId]),
        })),
      revokeApproval: (templateId) =>
        set((s) => {
          const next = new Set(s.sessionApprovedTemplates)
          next.delete(templateId)
          return { sessionApprovedTemplates: next }
        }),
      resetRun: () =>
        set({
          runId: null,
          uploadedTemplates: [],
          sourceFiles: [],
          asins: [],
          asinItems: [],
          resolvedProducts: [],
          manualEdits: {},
          findings: [],
          exportFiles: [],
          sessionApprovedTemplates: new Set(),
          previewRows: [],
          previewHeaders: [],
          singleResult: null,
          batchResponse: null,
          batchAsinText: '',
          singleInputs: { title: '', bulletsText: '', description: '', variantsText: '', groupRefId: '' },
        }),
      // Clears resolved/preview/validate/export data when template or ASINs change.
      // Keeps templates, sources and ASIN list so the user doesn't have to re-enter them.
      resetDownstream: () =>
        set({
          runId: null,
          resolvedProducts: [],
          manualEdits: {},
          findings: [],
          exportFiles: [],
          previewRows: [],
          previewHeaders: [],
        }),
    }),
    {
      name: 'wayfair-run-store',
      partialize: (state) => ({
        runId: state.runId,
        uploadedTemplates: state.uploadedTemplates,
        sourceFiles: state.sourceFiles,
        asins: state.asins,
        asinItems: state.asinItems,
        manualEdits: state.manualEdits,
        previewRows: state.previewRows,
        previewHeaders: state.previewHeaders,
        singleResult: state.singleResult,
        batchResponse: state.batchResponse,
        batchAsinText: state.batchAsinText,
        singleInputs: state.singleInputs,
      }),
    }
  )
)
