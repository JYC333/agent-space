import { Routes, Route } from 'react-router-dom'
import AgentsPage from './AgentsPage'
import AgentFormPage from './AgentFormPage'
import AgentDetailPage from './AgentDetailPage'
import AssistantChatPage from './AssistantChatPage'
import TemplateLibraryPage from './TemplateLibraryPage'
import TemplateDetailPage from './TemplateDetailPage'
import CreateFromTemplatePage from './CreateFromTemplatePage'

export default function AgentsModule() {
  return (
    <Routes>
      <Route index element={<AgentsPage />} />
      <Route path="new" element={<AgentFormPage />} />
      <Route path="templates" element={<TemplateLibraryPage />} />
      <Route path="templates/:templateId" element={<TemplateDetailPage />} />
      <Route path="templates/:templateId/use" element={<CreateFromTemplatePage />} />
      <Route path=":agentId/chat" element={<AssistantChatPage />} />
      <Route path=":agentId" element={<AgentDetailPage />} />
    </Routes>
  )
}
