import { describe, expect, it } from "vitest";
import { assertD1Compatible, MAX_ID_LIST } from "./db";

describe("assertD1Compatible", () => {
  it("101 パラメータで例外", () => {
    const params = Array.from({ length: 101 }, (_, i) => i);
    expect(() => assertD1Compatible("SELECT 1", params)).toThrow(/バインドパラメータ/);
  });

  it("100 パラメータは通る", () => {
    const params = Array.from({ length: 100 }, (_, i) => i);
    expect(() => assertD1Compatible("SELECT 1", params)).not.toThrow();
  });

  it("ATTACH を含む SQL は例外", () => {
    expect(() => assertD1Compatible("ATTACH DATABASE 'x' AS d")).toThrow(/ATTACH/);
  });

  it("ATTACH 時代の 'd.'/'c.' 接頭辞が残っていたら例外", () => {
    expect(() => assertD1Compatible("SELECT * FROM d.meas_year")).toThrow(/接頭辞/);
    expect(() => assertD1Compatible("SELECT * FROM c.cells")).toThrow(/接頭辞/);
  });

  it("観測キューブのエイリアス 'obs' は 'd.'/'c.' 接頭辞に誤検知しない", () => {
    expect(() => assertD1Compatible("SELECT obs.place_id FROM observation_agg obs")).not.toThrow();
  });

  it("IN (...) に8個以上の ? を並べると例外（json_each で渡す規約）", () => {
    const eightQ = Array.from({ length: 8 }, () => "?").join(",");
    expect(() => assertD1Compatible(`SELECT 1 WHERE x IN (${eightQ})`, Array.from({ length: 8 }, () => "a"))).toThrow(/IN/);
  });

  it("IN (...) が7個以下の ? なら通る", () => {
    const sevenQ = Array.from({ length: 7 }, () => "?").join(",");
    expect(() => assertD1Compatible(`SELECT 1 WHERE x IN (${sevenQ})`, Array.from({ length: 7 }, () => "a"))).not.toThrow();
  });

  it("LIKE のリテラルが51バイトで例外、50バイトは通る", () => {
    const bytes50 = "a".repeat(50);
    const bytes51 = "a".repeat(51);
    expect(() => assertD1Compatible(`SELECT 1 WHERE x LIKE '${bytes50}'`)).not.toThrow();
    expect(() => assertD1Compatible(`SELECT 1 WHERE x LIKE '${bytes51}'`)).toThrow(/LIKE/);
  });

  it("LIKE ? にバインドした51バイト文字列は例外、50バイトは通る", () => {
    expect(() => assertD1Compatible("SELECT 1 WHERE x LIKE ?", ["a".repeat(50)])).not.toThrow();
    expect(() => assertD1Compatible("SELECT 1 WHERE x LIKE ?", ["a".repeat(51)])).toThrow(/LIKE/);
  });

  it("LIKE ? の直前に別の ? があっても正しいパラメータを見る", () => {
    // 1個目の ? は関係ない値、2個目の ? が LIKE のバインド。
    expect(() => assertD1Compatible("SELECT 1 WHERE y = ? AND x LIKE ?", ["ok", "a".repeat(51)])).toThrow(/LIKE/);
    expect(() => assertD1Compatible("SELECT 1 WHERE y = ? AND x LIKE ?", ["a".repeat(51), "ok"])).not.toThrow();
  });

  it("マルチバイト文字は UTF-8 バイト長で数える", () => {
    // "あ" は UTF-8 で3バイト。17文字 = 51バイトで例外になる。
    expect(() => assertD1Compatible(`SELECT 1 WHERE x LIKE '${"あ".repeat(16)}'`)).not.toThrow(); // 48 bytes
    expect(() => assertD1Compatible(`SELECT 1 WHERE x LIKE '${"あ".repeat(17)}'`)).toThrow(/LIKE/); // 51 bytes
  });
});

describe("MAX_ID_LIST", () => {
  it("1000 である", () => {
    expect(MAX_ID_LIST).toBe(1000);
  });
});
