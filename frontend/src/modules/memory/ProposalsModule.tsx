import { Routes, Route } from 'react-router-dom'
import ProposalsPage from './ProposalsPage'
import ProposalDetailPage from './ProposalDetailPage'

export default function ProposalsModule() {
  return (
    <Routes>
      <Route index element={<ProposalsPage />} />
      <Route path=":proposalId" element={<ProposalDetailPage />} />
    </Routes>
  )
}
