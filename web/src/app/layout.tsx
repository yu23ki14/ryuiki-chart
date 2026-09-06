import type { Metadata } from "next";
import { Noto_Sans_JP, Geist_Mono } from "next/font/google";
import "./globals.css";
import { SiteNav } from "@/components/SiteNav";
import { AssistantPanel } from "@/components/assistant/AssistantPanel";
import { PageContextProvider } from "@/components/assistant/PageContextProvider";

const notoSansJp = Noto_Sans_JP({
  variable: "--font-noto-sans-jp",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
});

const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: { default: "流域カルテ | Watershed Chart", template: "%s | 流域カルテ" },
  description:
    "尾根から海まで（Ridge to Reef）の観測データを一枚のカルテにするモニタリングデータ基盤のデモ。神奈川県の公開データで構成。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja" className={`${notoSansJp.variable} ${geistMono.variable} h-full antialiased`}>
      {/* アプリシェル。高さを画面に固定し、スクロールは各画面の内側の箱が持つ。
          こうしないと、横に並べたペインの片方が伸びたときに行ごと（＝地図側も）伸びてしまう。 */}
      <body className="h-full overflow-hidden flex flex-col bg-paper text-ink">
        {/* 画面の状態（PageContext）をアシスタントに渡す配線。children はサーバコンポーネントのままでよい
            （children を渡すだけなら、それを包むこのコンポーネント自身だけが client になる）。 */}
        <PageContextProvider>
          <SiteNav />
          <main className="flex-1 flex flex-col min-h-0">{children}</main>
          <AssistantPanel />
        </PageContextProvider>
      </body>
    </html>
  );
}
