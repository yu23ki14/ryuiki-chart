/** 奄美の物語への導線。奄美を選んだとき（`region=jp-46`）だけ出す（Issue #105 §6）。依存を持たない（クライアントからも読む）。 */
export const AMAMI_STORY_REGION = "jp-46" as const;
export const AMAMI_STORY_HREF = `/stories/amami?region=${AMAMI_STORY_REGION}`;
export const AMAMI_STORY_LABEL = "奄美の物語";

export function showAmamiStory(region: string): boolean {
  return region === AMAMI_STORY_REGION;
}
