import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

if (!document.elementFromPoint) {
  document.elementFromPoint = () => document.body
}

if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList
}

if (!Range.prototype.getBoundingClientRect) {
  Range.prototype.getBoundingClientRect = () => new DOMRect()
}

if (!HTMLElement.prototype.getClientRects) {
  HTMLElement.prototype.getClientRects = () => [] as unknown as DOMRectList
}

if (!HTMLElement.prototype.getBoundingClientRect) {
  HTMLElement.prototype.getBoundingClientRect = () => new DOMRect()
}

afterEach(() => {
  cleanup()
  localStorage.clear()
})
