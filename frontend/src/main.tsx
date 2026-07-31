import React from 'react'
import { createRoot } from 'react-dom/client'

import { ProductApp } from './overview'
import './styles.css'
import './typography.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ProductApp />
  </React.StrictMode>,
)
