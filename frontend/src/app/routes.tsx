import type { CallApi } from '../types/callReview'
import { CallOverview } from '../features/call-overview/CallOverview'
import { Procedure } from '../features/procedure/Procedure'
import type { ApprovedKnowledgeApi } from '../types/knowledge'
import {
  ApprovedKnowledge,
  KnowledgeArticle,
} from '../features/approved-knowledge/ApprovedKnowledge'
import { Navigate, Outlet, Route, Routes, Link } from 'react-router'
import type { Viewer } from '../types/viewer'
import { AppLayout } from './layout/AppLayout'
import { AgentConversations } from '../features/conversations/AgentConversations'
import type { ConversationsApi } from '../features/conversations/conversations'
import { FindingReview } from '../features/review-queue/FindingReview'
import { ReviewQueue } from '../features/review-queue/ReviewQueue'
import type { TeamReviewApi } from '../features/review-queue/teamQueue'

function RouteMessage({ title, home }: { title: string; home: string }) {
  return (
    <>
      <h1>{title}</h1>
      <Link to={home}>Back to your conversations</Link>
    </>
  )
}

export function AppRoutes({
  viewer,
  conversationsApi,
  callApi = null,
  knowledgeApi = null,
  teamReviewApi = null,
}: {
  viewer: Viewer
  conversationsApi: ConversationsApi | null
  callApi?: CallApi | null
  knowledgeApi?: ApprovedKnowledgeApi | null
  teamReviewApi?: TeamReviewApi | null
}) {
  const home = `/${viewer.role}/conversations`

  return (
    <Routes>
      <Route element={<AppLayout viewer={viewer} />}>
        <Route index element={<Navigate to={home} replace />} />
        <Route
          path="agent"
          element={
            viewer.role === 'agent' ? (
              <Outlet />
            ) : (
              <RouteMessage
                title="Page unavailable for your role"
                home={home}
              />
            )
          }
        >
          <Route index element={<Navigate to="conversations" replace />} />
          <Route path="conversations">
            <Route
              index
              element={
                <AgentConversations viewer={viewer} api={conversationsApi} />
              }
            />
            <Route
              path=":conversationId"
              element={<CallOverview viewer={viewer} api={callApi} />}
            />
            <Route
              path=":conversationId/transcript"
              element={<Procedure viewer={viewer} api={callApi} />}
            />
            <Route
              path=":conversationId/findings/:findingId"
              element={<Procedure viewer={viewer} api={callApi} />}
            />
          </Route>
          <Route path="knowledge">
            <Route
              index
              element={<ApprovedKnowledge viewer={viewer} api={knowledgeApi} />}
            />
            <Route
              path=":entryId"
              element={<KnowledgeArticle viewer={viewer} api={knowledgeApi} />}
            />
          </Route>
        </Route>
        <Route
          path="manager"
          element={
            viewer.role === 'manager' ? (
              <Outlet />
            ) : (
              <RouteMessage
                title="Page unavailable for your role"
                home={home}
              />
            )
          }
        >
          <Route index element={<Navigate to="conversations" replace />} />
          <Route path="conversations">
            <Route
              index
              element={<ReviewQueue viewer={viewer} api={teamReviewApi} />}
            />
            <Route
              path=":conversationId/findings/:findingId"
              element={<FindingReview viewer={viewer} api={teamReviewApi} />}
            />
          </Route>
          <Route path="knowledge" element={<h1>Knowledge drafts</h1>} />
        </Route>
        <Route
          path="*"
          element={<RouteMessage title="Page not found" home={home} />}
        />
      </Route>
    </Routes>
  )
}
