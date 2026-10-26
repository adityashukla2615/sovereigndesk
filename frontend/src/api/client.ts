import { DEMO_FILES, STATIC_DEMO, demoUrl } from '../lib/staticDemo';
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
  // The static demo answers from the recording; it has no other endpoints.
  const file = STATIC_DEMO ? DEMO_FILES[path] : undefined;
  if (STATIC_DEMO && !file) throw new ApiError(404, `GET ${path} is not part of the static demo`);
  const url = file ? demoUrl(file) : path;
  const response = await fetch(url, { headers: { Accept: 'application/json' }, ...init });
  if (!response.ok) throw new ApiError(response.status, `GET ${path} failed: HTTP ${response.status}`);
  return (await response.json()) as GetResponse<P>;
}

type PostPath = {
  [P in keyof paths]: paths[P] extends { post: object } ? P : never;
}[keyof paths];

type JsonBody<Op> = Op extends { requestBody: { content: { 'application/json': infer Body } } }
  ? Body
  : never;

export type PostBody<P extends PostPath> = paths[P] extends { post: infer Op } ? JsonBody<Op> : never;
export type PostResponse<P extends PostPath> = paths[P] extends { post: infer Op } ? JsonOk<Op> : never;

export async function apiPost<P extends PostPath>(
  path: P,
  body: PostBody<P>,
  init?: { signal?: AbortSignal },
): Promise<PostResponse<P>> {
  if (STATIC_DEMO) {
    throw new ApiError(501, 'Editing needs the live terminal: run SovereignDesk locally (see the README)');
  }
  const response = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    ...init,
  });
  if (!response.ok) throw new ApiError(response.status, `POST ${path} failed: HTTP ${response.status}`);
  return (await response.json()) as PostResponse<P>;
}

export type Health = GetResponse<'/api/health'>;
export type ImpactRequest = PostBody<'/api/impact'>;
