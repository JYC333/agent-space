import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { SpaceProvider } from './contexts/SpaceContext'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider } from './contexts/ThemeContext'
import { TooltipProvider } from './components/ui/tooltip'
import Shell from './core/Shell'
import ErrorBoundary from './core/ErrorBoundary'
import { MODULE_REGISTRY } from './modules/registry'
import { Skeleton } from './components/ui/skeleton'
import LoginPage from './pages/LoginPage'
import AcceptInvitationPage from './pages/AcceptInvitationPage'
import { useAuth } from './contexts/AuthContext'

const HomeGalleryPage = lazy(() => import('./modules/home/HomeGalleryPage'))

function PageLoader() {
  return (
    <div className="space-y-3 p-6">
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  )
}

function SuspensePage({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<PageLoader />}>
        {children}
      </Suspense>
    </ErrorBoundary>
  )
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { currentUser, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) return <PageLoader />

  // Always redirect to login if user is not authenticated
  if (!currentUser) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

export default function App() {
  return (
    <ThemeProvider>
    <AuthProvider>
      <SpaceProvider>
        <TooltipProvider delayDuration={400}>
          <BrowserRouter>
            <Routes>
              {/* Public routes — outside Shell */}
              <Route path="/login" element={<LoginPage />} />
              <Route path="/invitations/:token" element={<AcceptInvitationPage />} />

              <Route path="/" element={<RequireAuth><Shell /></RequireAuth>}>
                {/* Home / App Gallery — default landing */}
                <Route
                  index
                  element={
                    <SuspensePage>
                      <HomeGalleryPage />
                    </SuspensePage>
                  }
                />

                {/* Module pages — auto-registered from MODULE_REGISTRY */}
                {MODULE_REGISTRY.map(({ path, component: Page, hasSubRoutes }) => (
                  <Route
                    key={path}
                    path={hasSubRoutes
                      ? path.replace(/^\//, '') + '/*'
                      : path.replace(/^\//, '')}
                    element={
                      <SuspensePage>
                        <Page />
                      </SuspensePage>
                    }
                  />
                ))}
              </Route>
            </Routes>
          </BrowserRouter>
        </TooltipProvider>
      </SpaceProvider>
    </AuthProvider>
    </ThemeProvider>
  )
}
