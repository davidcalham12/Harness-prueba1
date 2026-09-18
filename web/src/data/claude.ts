import type { SampleFn } from './generate'

/**
 * Reaching the viewer's Claude, when the page has been granted it.
 *
 * `window.claude.use('sample')` resolves the capability, or `null` when this
 * view cannot run it — not served, not granted, or failed to load, and the
 * three are indistinguishable by design. So the page is built to work without
 * it and lights the feature up if and when it arrives: the resolution happens
 * after the first render, never during it.
 */
declare global {
  interface Window {
    claude?: { use?: (name: string) => Promise<unknown> }
  }
}

export async function getSample(): Promise<SampleFn | null> {
  try {
    const fn = await window.claude?.use?.('sample')
    return typeof fn === 'function' ? (fn as SampleFn) : null
  } catch {
    return null
  }
}

export {}
