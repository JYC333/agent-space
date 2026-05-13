import { Routes, Route } from 'react-router-dom'
import ActivityInboxPage from './ActivityInboxPage'
import ActivityDetailPage from './ActivityDetailPage'

export default function ActivityModule() {
  return (
    <Routes>
      <Route index element={<ActivityInboxPage />} />
      <Route path=":activityId" element={<ActivityDetailPage />} />
    </Routes>
  )
}
