import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ViewErrorBoundary } from './components/ViewErrorBoundary'

window.addEventListener("unhandledrejection", (event) => {
  console.error("[unhandledrejection]", event.reason);
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ViewErrorBoundary label="Application">
      <App />
    </ViewErrorBoundary>
  </StrictMode>,
)
