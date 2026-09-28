import { describe, it, expect } from 'vitest';
import { citedSegments, isTerminal, sourceUrl, statusLabel, detailSchema } from '../src/domain';
describe('presentation contracts', () => {
  it('recognizes terminal states and preserves unknown statuses', () => {
    expect(isTerminal('SUCCEEDED')).toBe(true);
    expect(isTerminal('RUNNING')).toBe(false);
    expect(statusLabel('FAILED')).toBe('失败');
    expect(statusLabel('custom')).toBe('custom');
  });
  it('creates source page links without inventing anchors', () => {
    const evidence = {
      id: 'e',
      citation_id: 'e',
      document_id: 7,
      filename: 'a',
      page: 2,
      anchor: 'page',
      text: 'text',
    };
    expect(sourceUrl(evidence)).toBe('/api/documents/7/source#page=2');
    expect(sourceUrl({ ...evidence, page: null })).toBe('/api/documents/7/source#chunk-e');
  });
  it('separates clickable citations from plain text', () => {
    expect(citedSegments('收入[E:abc]。')).toEqual([
      { text: '收入', citation: false },
      { text: '[E:abc]', citation: true },
      { text: '。', citation: false },
    ]);
    expect(citedSegments('')).toEqual([]);
  });
  it('rejects malformed backend records', () => {
    expect(detailSchema.safeParse({ id: 'wrong' }).success).toBe(false);
  });
});
