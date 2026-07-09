import { Routes, Route } from 'react-router-dom'
import ProjectsPage from './ProjectsPage'
import ProjectDetailPage from './ProjectDetailPage'
import ProjectSourcesPage from './ProjectSourcesPage'

export default function ProjectsModule() {
  return (
    <Routes>
      <Route index element={<ProjectsPage />} />
      <Route path=":projectId/sources" element={<ProjectSourcesPage />} />
      <Route path=":projectId" element={<ProjectDetailPage />} />
    </Routes>
  )
}
