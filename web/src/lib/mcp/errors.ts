/** 入力の組み合わせの誤り（`tools.ts` と `tools-records.ts` が共有する。循環 import を避けるため別ファイル）。 */
export class McpInputError extends Error {}
