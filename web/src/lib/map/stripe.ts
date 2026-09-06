/**
 * 斜めストライプのタイル画像を作る（MapLibre の `fill-pattern` 用）。
 *
 * 使い道は「複数の実体が混ざっているが、比率は言えない」面の塗り分け。
 * 単色で塗ると比率のある面と見分けが付かず、片方の色で塗れば
 * 「その水源が主」という嘘になる（docs/WATER_SOURCE_MAP.md §6-3）。
 *
 * 色は必ず palette.ts の既存の系列色を渡すこと。ここで色を作らない。
 *
 * 生成物は `map.addImage(id, {width, height, data})` にそのまま渡せる RGBA。
 * canvas を使わないので SSR 中に呼ばれても落ちない。
 *
 * 継ぎ目について: 色を `(x + y) % N` で決めているので、x にも y にも N ずらすと
 * 同じ模様になる = タイルを敷き詰めても縞が途切れない。N は帯幅 × 色数。
 */

export interface StripeTile {
  width: number;
  height: number;
  data: Uint8Array;
}

/** 帯 1 本の幅（px）。細すぎると縮小時に潰れ、太すぎると小さい町丁目で 1 色に見える。 */
const BAND = 6;

function rgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const v =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  const n = Number.parseInt(v, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/**
 * 45度のストライプ。colors の順に帯が並ぶ。
 * colors が 1 色なら単色のタイルになる（呼び出し側で分岐しなくて済むように）。
 */
export function stripeTile(colors: readonly string[], band = BAND): StripeTile {
  const cs = colors.length > 0 ? colors : ["#000000"];
  const size = band * cs.length;
  const rgbs = cs.map(rgb);
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const [r, g, b] = rgbs[Math.floor(((x + y) % size) / band)];
      const i = (y * size + x) * 4;
      data[i] = r;
      data[i + 1] = g;
      data[i + 2] = b;
      data[i + 3] = 255;
    }
  }
  return { width: size, height: size, data };
}

/** 凡例の見本など、DOM 側で同じ縞を出すための CSS。角度も帯幅も stripeTile と揃える。 */
export function stripeCss(colors: readonly string[], band = BAND): string {
  const cs = colors.length > 0 ? colors : ["#000000"];
  const stops = cs.map((c, i) => `${c} ${i * band}px ${(i + 1) * band}px`).join(", ");
  // MapLibre は fill-pattern のテクスチャを上下反転して貼るので、タイルでは「/」向きの縞が
  // 画面では「\」向きに出る（実機で確認）。CSS で同じ向きにするのは 45deg。
  return `repeating-linear-gradient(45deg, ${stops})`;
}
