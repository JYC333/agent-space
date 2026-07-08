import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import { Skeleton } from '../../components/ui/skeleton'

const SourcesPage = lazy(() => import('./SourcesPage'))
const SourcePresetsPage = lazy(() => import('./sourcePresets/SourcePresetsPage'))
const SourceConnectionDetailPage = lazy(() => import('./SourceConnectionDetailPage'))

function PageFallback() {
  return (
    <div className="p-6 space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-64 w-full" />
    </div>
  )
}

export default function SourcesModule() {
  return (
    <Routes>
      <Route index element={<Suspense fallback={<PageFallback />}><SourcesPage /></Suspense>} />
      <Route path="source-presets" element={<Suspense fallback={<PageFallback />}><SourcePresetsPage /></Suspense>} />
      <Route path="sources/:connectionId" element={<Suspense fallback={<PageFallback />}><SourceConnectionDetailPage /></Suspense>} />
      <Route path="connections/:connectionId" element={<Suspense fallback={<PageFallback />}><SourceConnectionDetailPage /></Suspense>} />
    </Routes>
  )
}
