/**
 * `--v1compat-db`（design §1「診断用 v1互換キューブ」）: `data/db/v2_v1compat.sqlite`
 * （`scripts/b03_build_observation.py --include-synthetic` から作った、合成データを
 * 除外**しない** `observation_agg`）を2つ目の接続として開き、本番の v2 接続と
 * 全く同じ問い合わせを流して、`synthetic_excluded` の「差分の差分」判定
 * （`classify.ts`）に使う行を作る。
 *
 * `@/lib/cube/db-sqlite`（`sqliteCubeDb`）をそのまま使う——v1compat も
 * `registry.sqlite`/`ryuiki.sqlite` を ATTACH した通常の `CubeDb` で、
 * `adapters-v2.ts` の `runV2Query` を全く同じ形で呼べる（別ファイルを指すだけ）。
 */
import type { CubeDb } from "@/lib/cube";
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";

export interface V1CompatPaths {
  v1compat: string;
  registry: string;
  ryuiki: string;
}

let sharedDb: (CubeDb & { close(): void }) | undefined;

export function openV1CompatDb(paths: V1CompatPaths): CubeDb & { close(): void } {
  if (!sharedDb) {
    sharedDb = sqliteCubeDb({ v2: paths.v1compat, registry: paths.registry, ryuiki: paths.ryuiki });
  }
  return sharedDb;
}

export function closeV1CompatDb(): void {
  sharedDb?.close();
  sharedDb = undefined;
}
