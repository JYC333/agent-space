import { Routes, Route } from 'react-router-dom'
import ProjectsPage from './ProjectsPage'
import ProjectDetailPage from './ProjectDetailPage'
import ProjectSourcesPage from './ProjectSourcesPage'
import ProjectChatPage from './ProjectChatPage'
import ResearchReportPage from './ResearchReportPage'
import ResearchWorkspacePage from './ResearchWorkspacePage'

export default function ProjectsModule() {
  return (
    <Routes>
      <Route index element={<ProjectsPage />} />
      <Route path=":projectId/sources" element={<ProjectSourcesPage />} />
      <Route path=":projectId/chat" element={<ProjectChatPage />} />
      <Route path=":projectId/research/reports/:reportId" element={<ResearchReportPage />} />
      <Route path=":projectId/research" element={<ResearchWorkspacePage />} />
      <Route path=":projectId" element={<ProjectDetailPage />} />
    </Routes>
  )
}
