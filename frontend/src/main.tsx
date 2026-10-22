import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './app/App'
import { createDependencies } from './app/dependencies'
import './styles/tokens.css'
import './styles/global.css'
import './styles/controls.css'

const { viewerApi, conversationsApi } = createDependencies()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App viewerApi={viewerApi} conversationsApi={conversationsApi} />
    </BrowserRouter>
  </StrictMode>,
)
