import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import { Skeleton } from '../../components/ui/skeleton'

const IntakePage = lazy(() => import('./IntakePage'))
const SourcePresetsPage = lazy(() => import('./sourcePresets/SourcePresetsPage'))
const IntakeItemDetailPage = lazy(() => import('./IntakeItemDetailPage'))
const IntakeItemReaderPage = lazy(() => import('./IntakeItemReaderPage'))
const SourceConnectionDetailPage = lazy(() => import('./SourceConnectionDetailPage'))

function PageFallback() {
  return (
    <div className="p-6 space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-64 w-full" />
    </div>
  )
}

export default function IntakeModule() {
  return (
    <Routes>
      <Route index element={<Suspense fallback={<PageFallback />}><IntakePage /></Suspense>} />
      <Route path="source-presets" element={<Suspense fallback={<PageFallback />}><SourcePresetsPage /></Suspense>} />
      <Route path="sources/:connectionId" element={<Suspense fallback={<PageFallback />}><SourceConnectionDetailPage /></Suspense>} />
      <Route path="connections/:connectionId" element={<Suspense fallback={<PageFallback />}><SourceConnectionDetailPage /></Suspense>} />
      <Route path="items/:itemId" element={<Suspense fallback={<PageFallback />}><IntakeItemDetailPage /></Suspense>} />
      <Route path="items/:itemId/read" element={<Suspense fallback={<PageFallback />}><IntakeItemReaderPage /></Suspense>} />
    </Routes>
  )
}
