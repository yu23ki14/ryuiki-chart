import { describe, expect, it, vi } from "vitest";

// prompt.ts (と、それが import する db.ts 等) は `import "server-only"` を持つ。
// vitest は Node 環境で動くので、そのままだと server-only パッケージが例外を投げる
// （Next.js のバンドラだけが "react-server" 条件でこれを空モジュールに差し替える）。
// テストのためだけにここで無害化する。プロダクションコードは一切変えない。
vi.mock("server-only", () => ({}));

const { buildSystemPrompt } = await import("@/lib/ai/prompt");

/**
 * buildSystemPrompt() の全文スナップショット（docs/plans/PHASE_A.md §A-7）。
 *
 * 目的は「レジストリ由来に切り替えたときの差分を目で確認できるようにする」こと。
 * pageContext を渡さない呼び出し（画面文脈のブロックが空になる、最も安定した形）を対象にする。
 *
 * このスナップショットは切り替え前後で完全一致することを要求しない
 * （§A-7 の指示: 「レジストリから増えた語彙情報」だけの差分は許容される）。
 * 増えた場合は、何をなぜ増やしたかを実装の報告に書く。
 */
describe("buildSystemPrompt", () => {
  it("pageContext 無し", () => {
    expect(buildSystemPrompt()).toMatchSnapshot();
  });
});
