import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { flushOutbox } from './lib/api'

// Replay evidence writes that were recorded while offline. The server dedupes them
// with idempotency keys, so a double flush cannot create duplicate events.
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    void flushOutbox()
  })
  if (navigator.onLine) void flushOutbox()
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
