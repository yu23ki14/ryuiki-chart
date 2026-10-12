import { googleMapsUrl } from "@/lib/google-maps";

/** 地点名の横に置く「Google マップで開く」リンク。座標が無ければ何も出さない。 */
export function SiteMapLink({
  name,
  lat,
  lon,
  className = "",
}: {
  name: string;
  lat: number | null | undefined;
  lon: number | null | undefined;
  className?: string;
}) {
  const href = googleMapsUrl(lat, lon);
  if (!href) return null;
  const label = `${name} を Google マップで開く（新しいタブ）`;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={label}
      aria-label={label}
      className={`text-[11px] text-water-ink hover:underline whitespace-nowrap ${className}`}
    >
      Google マップ↗
    </a>
  );
}
