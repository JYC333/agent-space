import { Routes, Route } from 'react-router-dom'
import KnowledgePage from './KnowledgePage'
import KnowledgeDetailPage from './KnowledgeDetailPage'

export default function KnowledgeModule() {
  return (
    <Routes>
      <Route index element={<KnowledgePage />} />
      <Route path=":itemId" element={<KnowledgeDetailPage />} />
    </Routes>
  )
}
