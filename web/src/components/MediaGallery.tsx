import { useState } from 'react'
import type { Media } from '../types'

function Item({ m, n }: { m: Media; n: number }) {
  const [failed, setFailed] = useState(false)
  return (
    <figure>
      {failed ? <div className="media-fail">can't display<br /><code>{m.storage_url}</code></div>
        : m.type === 'video' ? <video src={m.view_url} controls onError={() => setFailed(true)} />
        : <a href={m.view_url} target="_blank" rel="noreferrer"><img src={m.view_url} alt={`media ${n}`} onError={() => setFailed(true)} /></a>}
      <figcaption>#{n} · {m.type} · <code>{m.id}</code></figcaption>
    </figure>
  )
}

export function MediaGallery({ media }: { media: Media[] }) {
  if (!media.length) return <p className="muted">No media uploaded for this return.</p>
  return <div className="gallery">{media.map((m, i) => <Item key={m.id} m={m} n={i + 1} />)}</div>
}

/** The seller's advertised product photos, shown next to the customer's media for comparison. */
export function ListingGallery({ images }: { images: { storage_url: string; view_url: string }[] }) {
  const [failed, setFailed] = useState<Record<string, boolean>>({})
  const shown = images.filter((i) => !failed[i.storage_url])
  if (!images.length) return <p className="muted">The listing has no images.</p>
  if (!shown.length) return <p className="muted">Listing images are set but cannot be displayed (e.g. gs:// placeholders): {images.length} stored.</p>
  return (
    <div className="gallery">
      {shown.map((i, n) => (
        <figure key={i.storage_url}>
          <a href={i.view_url} target="_blank" rel="noreferrer">
            <img src={i.view_url} alt={`listing ${n + 1}`} onError={() => setFailed((f) => ({ ...f, [i.storage_url]: true }))} />
          </a>
          <figcaption>listing #{n + 1}</figcaption>
        </figure>
      ))}
    </div>
  )
}
