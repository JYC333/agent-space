import { Routes, Route } from 'react-router-dom'
import MemoriesPage from './MemoriesPage'
import MemoryDetailPage from './MemoryDetailPage'

export default function MemoryModule() {
  return (
    <Routes>
      <Route index element={<MemoriesPage />} />
      <Route path=":memoryId" element={<MemoryDetailPage />} />
    </Routes>
  )
}
