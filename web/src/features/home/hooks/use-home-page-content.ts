/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import i18next from 'i18next'
import { useEffect, useState } from 'react'

import { isHttpUrl } from '@/lib/content-format'
import { handleServerError } from '@/lib/handle-server-error'
import { requireServerSuccess } from '@/lib/server-error-message'

import { getHomePageContent } from '../api'
import type { HomePageContentResult } from '../types'

const STORAGE_KEY = 'home_page_content'

/**
 * Hook to load and manage custom home page content
 * Supports both Markdown/HTML content and iframe URLs
 */
export function useHomePageContent(
  customHomeEnabled?: boolean | null
): HomePageContentResult {
  // null means never resolved; '' means the server chose the default page.
  const [snapshot, setSnapshot] = useState<string | null>(() => {
    if (customHomeEnabled === false) return null
    try {
      return localStorage.getItem(STORAGE_KEY)
    } catch {
      return null
    }
  })

  useEffect(() => {
    // The shared status request is still pending. An older server resolves
    // to undefined instead, in which case the content endpoint is authoritative.
    if (customHomeEnabled === null) return
    if (customHomeEnabled === false) {
      setSnapshot(null)
      try {
        localStorage.removeItem(STORAGE_KEY)
      } catch {
        /* optional cache */
      }
      return
    }
    let mounted = true

    const loadContent = async () => {
      try {
        const response = requireServerSuccess(await getHomePageContent())
        if (!mounted) return
        const fresh = response.data ?? ''
        setSnapshot(fresh)
        try {
          if (fresh) localStorage.setItem(STORAGE_KEY, fresh)
          else localStorage.removeItem(STORAGE_KEY)
        } catch {
          /* The fresh result still renders without persistence. */
        }
      } catch (error) {
        if (!mounted) return
        handleServerError(error, i18next.t('Failed to load home page content'))
        setSnapshot((previous) => previous ?? '')
      }
    }

    loadContent()

    return () => {
      mounted = false
    }
  }, [customHomeEnabled])

  if (customHomeEnabled === false) {
    return { content: '', isLoaded: true, isUrl: false }
  }
  const content = snapshot ?? ''

  return { content, isLoaded: snapshot !== null, isUrl: isHttpUrl(content) }
}
