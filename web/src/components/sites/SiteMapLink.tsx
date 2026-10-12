import { googleMapsUrl } from "@/lib/google-maps";

/** 地点名の横に置く「Google マップで開く」リンク。座標が無ければ何も出さない。 */
export function SiteMapLink({
  lat,
  lon,
  className = "",
}: {
  lat: number | null | undefined;
  lon: number | null | undefined;
  className?: string;
}) {
  const href = googleMapsUrl(lat, lon);
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title="Google マップで開く"
      aria-label="Google マップで開く"
      className={`text-[11px] text-water-ink hover:underline whitespace-nowrap ${className}`}
    >
      地図で見る
    </a>
  );
}
