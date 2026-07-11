import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ProjectChatPage from '../ProjectChatPage'
import { agentsApi } from '../../../api/client'

vi.mock('sonner',()=>({toast:{success:vi.fn(),error:vi.fn()}}))
vi.mock('../../../contexts/SpaceContext',()=>({useSpace:()=>({activeSpaceId:'space-1'})}))
vi.mock('../../../api/client',()=>({
  projectsApi:{get:vi.fn()},
  agentsApi:{getDefaultAssistant:vi.fn(),chat:vi.fn()},
  sessionsApi:{messages:vi.fn()},
}))
import { projectsApi, sessionsApi } from '../../../api/client'

const project={id:'project-1',space_id:'space-1',owner_user_id:'user-1',name:'Launch research',description:null,status:'active',current_focus:null,settings_json:{},archived_at:null,created_at:'',updated_at:''} as const
const agent={id:'agent-1',space_id:'space-1',created_by_user_id:null,name:'Assistant',description:null,visibility:'space_shared',role_instruction:null,status:'active',agent_kind:'system_assistant',current_version_id:'v1',source_template_id:null,source_template_version_id:null,model:null,adapter_type:'model_api',requires_model_provider:true,system_prompt:null,created_at:'',updated_at:''} as const

describe('ProjectChatPage',()=>{
  beforeEach(()=>{vi.clearAllMocks();Element.prototype.scrollTo=vi.fn();vi.mocked(projectsApi.get).mockResolvedValue(project as never);vi.mocked(agentsApi.getDefaultAssistant).mockResolvedValue(agent as never);vi.mocked(sessionsApi.messages).mockResolvedValue([])})
  it('sends managed chat turns with project scope and renders proposal previews',async()=>{
    vi.mocked(agentsApi.chat).mockResolvedValue({session_id:'session-1',run_id:'run-1',ok:true,reply:'I prepared a reviewed change.',action_previews:[{action_id:'project.source.propose_bind',status:'proposed',proposal_id:'proposal-1',proposal_type:'project_source_bind',title:'Bind source to project',risk_level:'medium'}]})
    render(<MemoryRouter initialEntries={['/projects/project-1/chat']}><Routes><Route path="/projects/:projectId/chat" element={<ProjectChatPage/>}/></Routes></MemoryRouter>)
    const input=await screen.findByPlaceholderText(/ask your assistant/i)
    fireEvent.change(input,{target:{value:'Add this source'}});fireEvent.keyDown(input,{key:'Enter',shiftKey:false})
    await waitFor(()=>expect(agentsApi.chat).toHaveBeenCalledWith('agent-1',{message:'Add this source',project_id:'project-1',session_id:undefined},{spaceId:'space-1'}))
    expect(await screen.findByText('Bind source to project')).toBeInTheDocument()
    expect(screen.getByRole('link',{name:/review proposal/i})).toHaveAttribute('href','/spaces/space-1/proposals/proposal-1')
  })
})
