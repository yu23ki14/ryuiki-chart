import { describe, it, expect, vi, afterEach } from "vitest";
import { streamText, toUIMessageStream, stepCountIs, simulateReadableStream } from "ai";
import { MockLanguageModelV3 } from "ai/test";
import { guardAssistantStream } from "./stream-guard";

vi.mock("server-only", () => ({}));

function model(texts: string[]) {
  return new MockLanguageModelV3({
    doStream: async () => ({
      stream: simulateReadableStream({
        chunks: [
          { type: "stream-start", warnings: [] },
          { type: "text-start", id: "t" },
          ...texts.map((delta) => ({ type: "text-delta" as const, id: "t", delta })),
          { type: "text-end", id: "t" },
          {
            type: "finish",
            finishReason: { unified: "stop", raw: "stop" },
            usage: {
              inputTokens: { total: 1, noCache: 1, cacheRead: 0, cacheWrite: 0 },
              outputTokens: { total: 1, text: 1, reasoning: 0 },
            },
          },
        ],
      }),
    }),
  });
}

type Part = { type: string; id?: string; delta?: string };

async function collect(texts: string[], guarded = true) {
  const result = streamText({
    model: model(texts),
    prompt: "hi",
    stopWhen: stepCountIs(2),
    ...(guarded ? { experimental_transform: guardAssistantStream() } : {}),
  });
  const parts: Part[] = [];
  const reader = toUIMessageStream({ stream: result.stream }).getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value as Part);
  }
  return parts;
}

const textOf = (parts: Part[]) =>
  parts.filter((p) => p.type === "text-delta").map((p) => p.delta).join("");

describe("guardAssistantStream", () => {
  afterEach(() => vi.restoreAllMocks());

  for (const guarded of [false, true]) {
    it(`finish-step と finish まで届いて閉じる (guard=${guarded})`, async () => {
      const parts = await collect(["こんにちは", "。"], guarded);
      expect(parts.slice(-3).map((p) => p.type)).toEqual(["text-end", "finish-step", "finish"]);
    });
  }

  it("生のツール呼び出しトークンを落とし、注記を最後の finish-step の後ろに足して閉じる", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const parts = await collect(["調べます。<|tool_calls_section_begin|>x"]);
    const text = textOf(parts);
    expect(text).not.toContain("<|");
    expect(text).toContain("打ち切りました");
    expect(parts.slice(-5).map((p) => [p.type, p.id])).toEqual([
      ["finish-step", undefined],
      ["text-start", "cutoff-note"],
      ["text-delta", "cutoff-note"],
      ["text-end", "cutoff-note"],
      ["finish", undefined],
    ]);
  });

  it("本文が空なら空パートを捨て、注記だけ足して finish で閉じる", async () => {
    const parts = await collect([]);
    expect(textOf(parts)).toContain("打ち切りました");
    expect(parts.filter((p) => p.type === "text-start")).toHaveLength(1);
    expect(parts.at(-1)?.type).toBe("finish");
  });
});
