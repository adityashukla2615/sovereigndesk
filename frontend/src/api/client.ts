import type { paths } from './schema';

/** Typed REST client over the generated OpenAPI schema (`py tasks.py api` regenerates it). */

type JsonOk<Op> = Op extends {
  responses: { 200: { content: { 'application/json': infer Body } } };
}
  ? Body
  : never;

type GetPath = {
  [P in keyof paths]: paths[P] extends { get: object } ? P : never;
}[keyof paths];

export type GetResponse<P extends GetPath> = paths[P] extends { get: infer Op } ? JsonOk<Op> : never;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function apiGet<P extends GetPath>(
  path: P,
  init?: { signal?: AbortSignal },
): Promise<GetResponse<P>> {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, ...init });
  if (!response.ok) throw new ApiError(response.status, `GET ${path} failed: HTTP ${response.status}`);
  return (await response.json()) as GetResponse<P>;
}

export type Health = GetResponse<'/api/health'>;
