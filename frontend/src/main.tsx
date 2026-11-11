import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './i18n' // Initialize i18n
import App from './App.tsx'
import { initLauncherEmbedding } from './utils/launcher'

// Before the first render, so the embedded layout and safe-area insets apply
// from the very first paint when the phone launcher opens us in an iframe.
initLauncherEmbedding()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
