# gbrain-dream Skill — 记忆整理与编译

## 触发条件

### 定时触发
- OpenClaw cron 表达式：`0 3 * * 0`（每周日凌晨 3:00）
- 触发范围：所有活跃租户

### 手动触发
管理员操作：
- `POST /admin/gbrain/dream` — 全租户整理
- `POST /admin/gbrain/dream?tenant_id=xxx` — 单租户整理

### 条件触发
- `gbrain_pages.timeline_count > 50` 时触发增量整理
- 用户显式请求"整理我的知识库"

## 输入格式

```json
{
  "trigger_type": "cron",
  "tenant_id": null,
  "dream_mode": "full",
  "max_pages_per_tenant": 100
}
```

`dream_mode` 选项：
- `full` — 全量整理（遍历所有页面，重写 compiled truth）
- `incremental` — 增量整理（仅处理 timeline_count > 10 的页面）
- `compact` — 压缩整理（合并旧 timeline，保留摘要）

## 处理逻辑

### 1. 扫描待整理页面

```sql
-- 全量模式
SELECT p.*, COUNT(t.id) as timeline_count
FROM gbrain_pages p
LEFT JOIN gbrain_timeline_entries t ON t.page_id = p.id
WHERE p.source_id IN (
  SELECT id FROM gbrain_sources
  WHERE ($1::uuid IS NULL OR tenant_id = $1)
)
GROUP BY p.id
HAVING COUNT(t.id) > 0
ORDER BY timeline_count DESC
LIMIT $2;

-- 增量模式（timeline > 10 的页面）
HAVING COUNT(t.id) > 10
```

### 2. Compiled Truth 重写

对于每个待整理页面：

```python
async def rewrite_compiled_truth(page, tenant_id):
    # 1. 读取所有 timeline entries
    timelines = await brain_ops.get_page_context(
        tenant_id, page.path,
        include_timeline=True, include_links=False
    )

    # 2. 按时间聚合生成摘要
    summary = generate_timeline_summary(timelines)

    # 3. 构建新的 compiled truth
    new_content = f"""## {page.title}

### 最新状态（{today}）
{summary.current_state}

### 关键事件时间线
{summary.key_events}

### 累计统计
{summary.statistics}
"""

    # 4. 更新页面内容
    await brain_ops.upsert_page(
        tenant_id=tenant_id,
        path=page.path,
        title=page.title,
        content=new_content,
        page_type=page.page_type,
        metadata={**page.metadata, "last_dream_at": now},
    )
```

### 3. Timeline 压缩（compact 模式）

超过 90 天的旧 timeline 条目合并为月度摘要：

```sql
-- 查找超过 90 天的 timeline
SELECT * FROM gbrain_timeline_entries
WHERE page_id = $1
  AND event_date < NOW() - INTERVAL '90 days'
ORDER BY event_date ASC;

-- 压缩为月度汇总条目
INSERT INTO gbrain_timeline_entries (
  page_id, event_date, event_type, title, content, importance
) VALUES (
  $1,
  DATE_TRUNC('month', MIN(event_date)),
  'COMPACT_SUMMARY',
  '{月份} 交易汇总',
  '{汇总内容}',
  3
);

-- 删除原始条目（或标记为 archived）
UPDATE gbrain_timeline_entries
SET event_type = 'ARCHIVED'
WHERE page_id = $1
  AND event_date < NOW() - INTERVAL '90 days';
```

### 4. 孤儿链接清理

```sql
-- 清理指向已删除页面的链接
DELETE FROM gbrain_links
WHERE source_page_id NOT IN (SELECT id FROM gbrain_pages)
   OR target_page_id NOT IN (SELECT id FROM gbrain_pages);

-- 清理没有反向链接的孤立页面（inbox 除外）
DELETE FROM gbrain_pages
WHERE id NOT IN (
  SELECT DISTINCT target_page_id FROM gbrain_links
)
AND path NOT LIKE 'inbox/%'
AND created_at < NOW() - INTERVAL '30 days';
```

### 5. 搜索缓存刷新

```sql
-- 清除过期搜索缓存
DELETE FROM gbrain_search_cache
WHERE created_at < NOW() - INTERVAL '7 days';

-- 预热常用搜索
SELECT * FROM gbrain_search_cache
ORDER BY hit_count DESC
LIMIT 20;
```

## 输出格式

### 执行报告
```json
{
  "run_id": "uuid",
  "trigger_type": "cron",
  "dream_mode": "full",
  "started_at": "2024-01-15T03:00:00Z",
  "completed_at": "2024-01-15T03:15:00Z",
  "duration_ms": 900000,
  "summary": {
    "tenants_processed": 15,
    "pages_rewritten": 127,
    "timelines_compacted": 342,
    "orphan_links_removed": 23,
    "orphan_pages_removed": 5,
    "cache_entries_cleared": 156
  },
  "tenant_breakdown": {
    "tenant-abc": {
      "pages_rewritten": 12,
      "timelines_compacted": 45,
      "duration_ms": 72000
    }
  }
}
```

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| 单页面整理失败 | 跳过该页面，记录日志，继续处理其他页面 |
| OpenAI 调用失败 | 使用模板化摘要替代 AI 生成 |
| 数据库超时 | 分批处理，每批 20 个页面 |
| 租户数据量过大 | 仅处理最近 100 个活跃页面 |

## 数据库操作

- **gbrain_pages**：SELECT（扫描）、UPDATE（重写内容）
- **gbrain_timeline_entries**：SELECT（读取）、INSERT（汇总）、UPDATE（标记 archived）
- **gbrain_links**：DELETE（清理孤儿链接）
- **gbrain_search_cache**：DELETE（清除过期缓存）
- **memory_entity_bridge**：UPDATE（sync_status）
- **job_runs**：INSERT（执行日志）

## 扩展计划

| 阶段 | 功能 |
|------|------|
| Phase 1 | 基础整理（当前）：重写 compiled truth + 压缩 timeline |
| Phase 2 | AI 辅助整理：使用 LLM 生成洞察总结 |
| Phase 3 | 跨页面关联发现：自动创建新链接 |
| Phase 4 | 知识图谱可视化：导出租户知识图谱 |
