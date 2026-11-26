import { AssessmentRoute } from './AssessmentRoute'
import { CallOverview } from '../features/call-overview/CallOverview'
import { Procedure } from '../features/procedure/Procedure'
import {
  ApprovedKnowledge,
  KnowledgeArticle,
} from '../features/approved-knowledge/ApprovedKnowledge'
import { Navigate, Outlet, Route, Routes } from 'react-router'
import { BackLink } from '../components/BackLink'
import type { Viewer } from '../types/viewer'
import { AppLayout } from './layout/AppLayout'
import { AgentConversations } from '../features/conversations/AgentConversations'
import { FindingReview } from '../features/review-queue/FindingReview'
import { ReviewQueue } from '../features/review-queue/ReviewQueue'
import type { WorkspaceDependencies } from './dependencies'
import { KnowledgeDrafts } from '../features/knowledge-drafts/KnowledgeDrafts'
import { KnowledgeReview } from '../features/knowledge-drafts/KnowledgeReview'
import { demoScorecardsEnabled } from '../lib/demoLogin'

function RouteMessage({ title, home }: { title: string; home: string }) {
  return (
    <>
      <h1>{title}</h1>
      <BackLink to={home}>Back to your conversations</BackLink>
    </>
  )
}

export function AppRoutes({
  viewer,
  onSwitchProfile,
  conversationsApi = null,
  callApi = null,
  knowledgeApi = null,
  teamReviewApi = null,
  knowledgeReviewApi = null,
}: Partial<WorkspaceDependencies> & {
  viewer: Viewer
  onSwitchProfile?: () => void
}) {
  const home = `/${viewer.role}/conversations`
  const simulation = demoScorecardsEnabled()

  return (
    <Routes>
      <Route element={<AppLayout viewer={viewer} onSwitchProfile={onSwitchProfile} />}>
        <Route index element={<Navigate to={home} replace />} />
        {(['agent', 'manager'] as const).map((role) => {
          const isAgent = role === 'agent'
          const agentEvidence = <Procedure viewer={viewer} api={callApi} />
          return (
            <Route key={role} path={role} element={
              viewer.role === role ? <Outlet /> : <RouteMessage title="Page unavailable for your role" home={home} />
            }>
              <Route index element={<Navigate to="conversations" replace />} />
              <Route path="conversations">
                <Route index element={isAgent ? (
                  <AgentConversations viewer={viewer} api={conversationsApi} simulation={simulation} />
                ) : (
                  <ReviewQueue viewer={viewer} api={teamReviewApi} simulation={simulation} />
                )} />
                <Route path=":conversationId" element={
                  <CallOverview viewer={viewer} api={isAgent ? callApi : null} managerApi={teamReviewApi} />
                } />
                {isAgent && <Route path=":conversationId/transcript" element={agentEvidence} />}
                <Route path=":conversationId/assessments/:category" element={
                  <AssessmentRoute viewer={viewer} api={callApi} managerApi={teamReviewApi} />
                } />
                <Route path=":conversationId/findings/:findingId" element={isAgent ? agentEvidence : (
                  <FindingReview viewer={viewer} api={teamReviewApi} />
                )} />
              </Route>
              <Route path="knowledge">
                <Route index element={isAgent ? (
                  <ApprovedKnowledge viewer={viewer} api={knowledgeApi} />
                ) : (
                  <KnowledgeDrafts viewer={viewer} api={knowledgeReviewApi} />
                )} />
                <Route path=":entryId" element={isAgent ? (
                  <KnowledgeArticle viewer={viewer} api={knowledgeApi} />
                ) : (
                  <KnowledgeReview viewer={viewer} api={knowledgeReviewApi} />
                )} />
              </Route>
            </Route>
          )
        })}
        <Route
          path="*"
          element={<RouteMessage title="Page not found" home={home} />}
        />
      </Route>
    </Routes>
  )
}
