import { z } from 'zod';
export const documentSchema = z.object({
  id: z.number(),
  filename: z.string(),
  status: z.string(),
  chunk_count: z.number(),
  storage_scope: z.enum(['LIBRARY', 'TASK']),
  error: z.string().nullish(),
});
export const taskSchema = z.object({
  id: z.number(),
  instruction: z.string(),
  status: z.string(),
  session_id: z.number(),
  result: z.string().nullish(),
  error: z.string().nullish(),
  version: z.number(),
  review_status: z.string(),
});
export const evidenceSchema = z.object({
  id: z.string(),
  citation_id: z.string(),
  document_id: z.number(),
  filename: z.string(),
  page: z.number().nullable(),
  anchor: z.string(),
  text: z.string(),
});
export const detailSchema = taskSchema.extend({
  agents: z.array(
    z.object({
      id: z.string(),
      parent_id: z.string().nullish(),
      name: z.string(),
      status: z.string(),
      steps: z.number(),
      prompt_tokens: z.number(),
      completion_tokens: z.number(),
    })
  ),
  tools: z.array(
    z.object({
      id: z.string(),
      agent_id: z.string(),
      name: z.string(),
      arguments: z.string(),
      result: z.string().nullish(),
      status: z.string(),
      duration_ms: z.number(),
    })
  ),
  evidence: z.array(evidenceSchema),
  reviews: z.array(
    z.object({ id: z.number(), decision: z.string(), note: z.string(), created_at: z.string() })
  ),
});
export const sessionSchema = z.object({ id: z.number(), title: z.string() });
export type Document = z.infer<typeof documentSchema>;
export type Task = z.infer<typeof taskSchema>;
export type Detail = z.infer<typeof detailSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export const isTerminal = (status: string): boolean =>
  ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(status);
export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    READY: '可检索',
    INDEXING: '索引中',
    QUEUED: '排队中',
    RUNNING: '执行中',
    SUCCEEDED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
    PENDING: '待审阅',
    CONFIRMED: '已确认',
    CORRECTED: '已修正',
  };
  return labels[status] ?? status;
}
export function sourceUrl(evidence: Evidence): string {
  return `/api/documents/${evidence.document_id}/source${evidence.page === null ? `#chunk-${evidence.id}` : `#page=${evidence.page}`}`;
}
export function citedSegments(text: string): { text: string; citation: boolean }[] {
  return text
    .split(/(\[E:[^\]]+\])/g)
    .filter(Boolean)
    .map((part) => ({ text: part, citation: part.startsWith('[E:') && part.endsWith(']') }));
}
