import { Routes, Route } from 'react-router-dom'
import EvolutionPage from './EvolutionPage'
import EvolutionInboxPage from './EvolutionInboxPage'

export default function EvolutionModule() {
  return (
    <Routes>
      <Route index element={<EvolutionPage />} />
      <Route path="inbox" element={<EvolutionInboxPage />} />
    </Routes>
  )
}
