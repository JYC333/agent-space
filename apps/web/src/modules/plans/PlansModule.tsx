import { Routes, Route } from 'react-router-dom'
import PlansPage from './PlansPage'
import PlanDetailPage from './PlanDetailPage'

export default function PlansModule() {
  return (
    <Routes>
      <Route index element={<PlansPage />} />
      <Route path=":planId" element={<PlanDetailPage />} />
    </Routes>
  )
}
