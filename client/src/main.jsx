import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/figtree/400'
import '@fontsource/figtree/500'
import '@fontsource/figtree/600'
import '@fontsource/figtree/700'
import '@fontsource/figtree/800'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
