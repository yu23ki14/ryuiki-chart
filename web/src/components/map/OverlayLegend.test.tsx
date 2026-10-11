import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { OverlayLegend } from "./OverlayLegend";
import { OVERLAYS } from "@/lib/map/overlay-layers";

const [hazard, a10] = OVERLAYS;
const html = (zoom: number | null, data = {}) =>
  renderToStaticMarkup(<OverlayLegend active={[hazard, a10]} zoom={zoom} data={data} />);

describe("OverlayLegend", () => {
  it("色には文字ラベルを添える", () => {
    const h = html(12);
    for (const t of ["警戒区域", "特別警戒区域", "特別警戒区域は警戒区域の内側にある", "公園区域", "特別地域", "特別保護地区"]) {
      expect(h).toContain(t);
    }
  });
  it("zoom が足りないときは「拡大すると表示される」", () => {
    expect(html(10)).toContain("拡大すると表示される");
    expect(html(12)).not.toContain("拡大すると表示される");
  });
  it("truncated と出典の note を出す", () => {
    const h = html(12, {
      hazard: { truncated: true, sources: [{ source_id: "x", note: "面積を足さない" }] },
    });
    expect(h).toContain("表示範囲に収まらない分は省略した");
    expect(h).toContain("面積を足さない");
  });
  it("何も有効でなければ何も出さない", () => {
    expect(renderToStaticMarkup(<OverlayLegend active={[]} zoom={12} data={{}} />)).toBe("");
  });
});
