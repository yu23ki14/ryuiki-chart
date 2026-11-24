import Database from "better-sqlite3";
import { describe, expect, it } from "vitest";
import { orderByForeignKeys, referencedOutside } from "./fk-order.mjs";
import { applyMigrations } from "@/lib/cube/__fixtures__/cube-fixture";

describe("orderByForeignKeys", () => {
  it("親を先に、関係の無い表は入力の順のまま", () => {
    const db = new Database(":memory:");
    db.exec("CREATE TABLE a (id TEXT PRIMARY KEY); CREATE TABLE b (id TEXT, a_id TEXT REFERENCES a(id)); CREATE TABLE c (id TEXT)");
    expect(orderByForeignKeys(db, ["a", "b", "c"])).toEqual(["a", "b", "c"]);
    expect(orderByForeignKeys(db, ["b", "c", "a"])).toEqual(["c", "a", "b"]);
    expect(orderByForeignKeys(db, ["b", "c"])).toEqual(["b", "c"]); // 対象外の親は無視
  });

  it("循環は例外", () => {
    const db = new Database(":memory:");
    db.exec("CREATE TABLE x (id TEXT PRIMARY KEY, y TEXT REFERENCES y(id)); CREATE TABLE y (id TEXT PRIMARY KEY, x TEXT REFERENCES x(id))");
    expect(() => orderByForeignKeys(db, ["x", "y"])).toThrow(/循環/);
  });

  it("マイグレーション後の全表で、どの子表も親より後に並ぶ（広報誌の表を含む）", () => {
    const db = new Database(":memory:");
    applyMigrations(db);
    const all = (db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all() as { name: string }[]).map((r) => r.name);
    const order = orderByForeignKeys(db, all);
    const pos = new Map(order.map((t, i) => [t, i]));
    for (const t of all) {
      for (const fk of db.prepare(`PRAGMA foreign_key_list("${t}")`).all() as { table: string }[]) {
        if (fk.table !== t) expect(pos.get(fk.table)!, `${fk.table} -> ${t}`).toBeLessThan(pos.get(t)!);
      }
    }
    for (const [parent, child] of [
      ["periodical_series", "periodical_issues"], ["documents", "periodical_issue_files"], ["periodical_issues", "document_articles"],
      ["document_articles", "document_article_topics"], ["document_articles", "document_article_places"],
    ]) {
      expect(pos.get(parent)!).toBeLessThan(pos.get(child)!);
    }
  });
});

describe("referencedOutside", () => {
  it("指定した表を参照する表がリストの外にあれば返す", () => {
    const db = new Database(":memory:");
    db.exec("CREATE TABLE documents (id TEXT PRIMARY KEY); CREATE TABLE cells (id TEXT, d TEXT REFERENCES documents(id)); CREATE TABLE notes (id TEXT, d TEXT REFERENCES documents(id))");
    expect(referencedOutside(db, ["documents", "notes"])).toEqual([{ child: "cells", parent: "documents" }]);
    expect(referencedOutside(db, ["documents", "notes", "cells"])).toEqual([]);
    expect(referencedOutside(db, ["cells"])).toEqual([]);
  });
  it("マイグレーション後: documents だけを指定すると cells などが外にあるとして止まる", () => {
    const db = new Database(":memory:");
    applyMigrations(db);
    expect(referencedOutside(db, ["documents"]).map((o) => o.child)).toContain("cells");
  });
});
