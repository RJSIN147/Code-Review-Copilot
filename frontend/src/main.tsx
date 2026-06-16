import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { SWRConfig } from 'swr'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SWRConfig
      value={{
        refreshWhenHidden: false,
        revalidateOnFocus: true,
        errorRetryCount: 3,
      }}
    >
      <App />
    </SWRConfig>
  </StrictMode>,
)
