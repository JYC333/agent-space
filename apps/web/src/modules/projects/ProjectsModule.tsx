import { Routes, Route } from 'react-router-dom'
import ProjectsPage from './ProjectsPage'
import ProjectDetailPage from './ProjectDetailPage'
import ProjectSourcesPage from './ProjectSourcesPage'
import ProjectChatPage from './ProjectChatPage'

export default function ProjectsModule() {
  return (
    <Routes>
      <Route index element={<ProjectsPage />} />
      <Route path=":projectId/sources" element={<ProjectSourcesPage />} />
      <Route path=":projectId/chat" element={<ProjectChatPage />} />
      <Route path=":projectId" element={<ProjectDetailPage />} />
    </Routes>
  )
}
