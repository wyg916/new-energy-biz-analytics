import { describe, expect, it } from 'vitest'
import { formatMetric } from '../src/format'

describe('metric formatting', () => {
  it('renders ratios as percentages', () => expect(formatMetric('gross_margin', 0.2345)).toBe('23.4%'))
  it('keeps null truthful', () => expect(formatMetric('gross_margin', null)).toBe('数据不足'))
  it('renders counts as integers', () => expect(formatMetric('active_user_count', 1234)).toContain('1'))
})
