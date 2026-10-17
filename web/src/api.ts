import type { DemoOrder, DemoProduct, QueueItem, ReturnDetail, Cause } from './types'

export const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* keep statusText */ }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
})

export const api = {
  products: () => req<DemoProduct[]>('/demo/products'),
  orders: (productId: string) => req<DemoOrder[]>(`/demo/orders?product_id=${productId}`),
  queue: (status?: string) => req<QueueItem[]>(`/returns${status ? `?status=${status}` : ''}`),
  detail: (id: string) => req<ReturnDetail>(`/returns/${id}`),

  /** signed URL -> PUT the file straight to it -> returns the storage_url to send with the return */
  async uploadMedia(file: File): Promise<string> {
    const signed = await req<{ upload_url: string; storage_url: string }>(
      '/media/upload-url', json('POST', { content_type: file.type }))
    const put = await fetch(signed.upload_url, { method: 'PUT', headers: { 'content-type': file.type }, body: file })
    if (!put.ok) throw new Error(`upload failed (${put.status}): ${await put.text()}`)
    return signed.storage_url
  },
  createReturn: (b: { order_id: string; stated_reason: string; comment: string | null; media: { storage_url: string }[] }) =>
    req<{ return_id: string; status: string; media_count: number }>('/returns', json('POST', b)),
  review: (id: string, b: { decision: 'accepted' | 'rejected'; final_root_cause?: Cause; note?: string; reviewer: string }) =>
    req(`/returns/${id}/review`, json('POST', b)),
  reanalyze: (id: string) => req(`/returns/${id}/reanalyze`, { method: 'POST' }),
}
