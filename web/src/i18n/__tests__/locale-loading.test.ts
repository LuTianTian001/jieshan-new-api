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
import { expect, test, vi } from 'vitest'

// Exercise a fresh real instance: the shared test setup has already selected
// English on its singleton, which would bypass browser language detection.
vi.mock('i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('i18next')>()
  return { ...actual, default: actual.createInstance() }
})

test('a Chinese visitor gets the selected dictionary, keeps the English fallback and can switch languages', async () => {
  window.localStorage.setItem('i18nextLng', 'zh-CN')
  const config = await import('../config')
  await config.i18nReady
  const i18n = config.default
  expect(i18n.t('Unified API Gateway for')).toBe('统一 API 网关，服务于')
  expect(i18n.hasResourceBundle('fr', 'translation')).toBe(false)
  for (const [language, label] of [
    ['zhTW', '返回登入'],
    ['ja', 'ログインに戻る'],
    ['fr', 'Retour à la connexion'],
    ['ru', 'Вернуться ко входу'],
    ['vi', 'Quay lại đăng nhập'],
    ['en', 'Return to login'],
    ['unsupported', 'Return to login'],
    ['zhCN', '返回登录'],
  ]) {
    await i18n.changeLanguage(language)
    expect(i18n.t('auth.resetPasswordConfirm.backToLogin')).toBe(label)
  }
})
