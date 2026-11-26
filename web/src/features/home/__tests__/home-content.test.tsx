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
import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { getHomePageContent } from '../api'
import { useHomePageContent } from '../hooks/use-home-page-content'
import type { HomePageContentResponse } from '../types'

vi.mock('../api', () => ({ getHomePageContent: vi.fn() }))

function pendingContent() {
  let resolve!: (value: HomePageContentResponse) => void
  const promise = new Promise<HomePageContentResponse>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

afterEach(() => {
  localStorage.removeItem('home_page_content')
  vi.mocked(getHomePageContent).mockReset()
})

test('a default site immediately shows its landing page even with stale custom content', () => {
  localStorage.setItem('home_page_content', 'https://former.example/')
  vi.mocked(getHomePageContent).mockReturnValue(new Promise(() => {}))
  const { result } = renderHook(() => useHomePageContent(false))

  expect(result.current).toEqual({ content: '', isLoaded: true, isUrl: false })
  expect(getHomePageContent).not.toHaveBeenCalled()
})

test('a cold default site reuses the pending status check without fetching home content', () => {
  const { result, rerender } = renderHook(
    (enabled: boolean | null) => useHomePageContent(enabled),
    { initialProps: null as boolean | null }
  )
  expect(getHomePageContent).not.toHaveBeenCalled()
  rerender(false)
  expect(result.current.isLoaded).toBe(true)
  expect(getHomePageContent).not.toHaveBeenCalled()
})

test('a returning visitor sees the cached custom page while its replacement is fetched', async () => {
  localStorage.setItem('home_page_content', 'https://previous.example/')
  const response = pendingContent()
  vi.mocked(getHomePageContent).mockReturnValue(response.promise)
  const { result } = renderHook(() => useHomePageContent(true))

  expect(result.current).toEqual({
    content: 'https://previous.example/',
    isLoaded: true,
    isUrl: true,
  })
  await act(async () => response.resolve({ success: true, data: '# Updated' }))
  expect(result.current).toEqual({
    content: '# Updated',
    isLoaded: true,
    isUrl: false,
  })
})

test('a first-time visitor to a custom or older site waits for its real content', async () => {
  const response = pendingContent()
  vi.mocked(getHomePageContent).mockReturnValue(response.promise)
  const { result } = renderHook(() => useHomePageContent(undefined))

  expect(result.current.isLoaded).toBe(false)
  await act(async () =>
    response.resolve({ success: true, data: '<p>Hello</p>' })
  )
  expect(result.current).toEqual({
    content: '<p>Hello</p>',
    isLoaded: true,
    isUrl: false,
  })
})

test('disabling a custom page wins over an older in-flight response', async () => {
  const response = pendingContent()
  vi.mocked(getHomePageContent).mockReturnValue(response.promise)
  const { result, rerender } = renderHook(
    (enabled: boolean) => useHomePageContent(enabled),
    { initialProps: true }
  )
  rerender(false)
  await act(async () =>
    response.resolve({ success: true, data: 'stale content' })
  )
  expect(result.current).toEqual({ content: '', isLoaded: true, isUrl: false })
  expect(localStorage.getItem('home_page_content')).toBeNull()
})
