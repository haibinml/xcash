import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { MetadataProvider } from './context/MetadataProvider.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <MetadataProvider>
      <App />
    </MetadataProvider>
  </StrictMode>,
)
