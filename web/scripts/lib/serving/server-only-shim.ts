// `register-aliases.mjs` が "server-only" の解決先をここに差し替える。中身は
// `node_modules/server-only/empty.js`（Next.js が "react-server" 条件下で使う方）と
// 同じく空でよい——import はするが何も export しない。
export {};
