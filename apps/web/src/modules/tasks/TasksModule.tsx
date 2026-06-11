import { Routes, Route } from 'react-router-dom'
import TasksPage from './TasksPage'
import TaskDetailPage from './TaskDetailPage'

export default function TasksModule() {
  return (
    <Routes>
      <Route index element={<TasksPage />} />
      <Route path=":taskId" element={<TaskDetailPage />} />
    </Routes>
  )
}
