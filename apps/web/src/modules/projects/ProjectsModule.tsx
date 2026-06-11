import { Routes, Route } from 'react-router-dom'
import ProjectsPage from './ProjectsPage'
import ProjectDetailPage from './ProjectDetailPage'

export default function ProjectsModule() {
  return (
    <Routes>
      <Route index element={<ProjectsPage />} />
      <Route path=":projectId" element={<ProjectDetailPage />} />
    </Routes>
  )
}
