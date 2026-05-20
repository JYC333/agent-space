import { Routes, Route } from 'react-router-dom'
import AgentsPage from './AgentsPage'
import AgentFormPage from './AgentFormPage'
import AgentDetailPage from './AgentDetailPage'

export default function AgentsModule() {
  return (
    <Routes>
      <Route index element={<AgentsPage />} />
      <Route path="new" element={<AgentFormPage />} />
      <Route path=":agentId" element={<AgentDetailPage />} />
      <Route path=":agentId/edit" element={<AgentFormPage />} />
    </Routes>
  )
}
