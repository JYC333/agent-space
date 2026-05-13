import { Routes, Route } from 'react-router-dom'
import ArtifactsPage from './ArtifactsPage'
import ArtifactDetailPage from './ArtifactDetailPage'

export default function ArtifactsModule() {
  return (
    <Routes>
      <Route index element={<ArtifactsPage />} />
      <Route path=":artifactId" element={<ArtifactDetailPage />} />
    </Routes>
  )
}
