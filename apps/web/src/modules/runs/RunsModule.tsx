import { Routes, Route } from 'react-router-dom'
import RunsPage from './RunsPage'
import RunDetailPage from './RunDetailPage'

export default function RunsModule() {
  return (
    <Routes>
      <Route index element={<RunsPage />} />
      <Route path=":runId" element={<RunDetailPage />} />
    </Routes>
  )
}
