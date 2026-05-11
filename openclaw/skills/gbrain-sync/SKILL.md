# gbrain-sync Skill — 记忆同步队列消费

## 触发条件

### 定时触发
- OpenClaw cron 表达式：`*/5 * * * *`（每 5 分钟）
- 触发范围：所有租户

### 手动触发
管理员通过管理后台或 API 触发：
- `POST /admin/gbrain/sync` — 立即执行同步
- `POST /admin/gbrain/sync?tenant_id=xxx` — 单租户强制同步

### 条件触发
- SyncQueue 积压超过 `sync_batch_size * 2` 时自动触发
- 系统启动时执行一次全量同步检查

## 输入格式

### 自动触发
由 cron 触发器传递：
```json
{
  "trigger_type": "cron",
  "sync_mode": "batch",
  "max_batch_size": 10,
  "tenant_id": null
}
```

### 手动触发
```json
{
  "trigger_type": "manual",
  "sync_mode": "batch",
  "max_batch_size": 50,
  "tenant_id": "uuid-or-null"
}
```

## 处理逻辑

### 1. 读取待同步信号

从 `memory_sync_log` 表中读取 `sync_status = 'pending'` 的记录：

```sql
SELECT * FROM memory_sync_log
WHERE sync_status = 'pending'
  AND ($1::uuid IS NULL OR tenant_id = $1)
ORDER BY created_at ASC
LIMIT $2;
```

### 2. 批量处理

```python
for signal in pending_signals:
    try:
        if signal.operation == 'upsert_page':
            await brain_ops.upsert_page(
                tenant_id=signal.tenant_id,
                path=signal.path,
                title=signal.title,
                content=signal.content,
                page_type=signal.page_type,
                metadata=signal.metadata,
            )
        elif signal.operation == 'add_timeline':
            await brain_ops.add_timeline_entry(
                tenant_id=signal.tenant_id,
                path=signal.path,
                event_date=signal.event_date,
                event_type=signal.event_type,
                title=signal.timeline_title,
                content=signal.timeline_content,
                importance=signal.importance,
                metadata=signal.metadata,
            )
        elif signal.operation == 'create_link':
            await brain_ops.create_link(
                tenant_id=signal.tenant_id,
                source_path=signal.source_path,
                target_path=signal.target_path,
                link_type=signal.link_type,
                confidence=signal.confidence,
            )

        # 标记成功
        await mark_sync_success(signal.id)

    except Exception as e:
        # 重试计数 +1
        await mark_sync_failed(signal.id, str(e))
```

### 3. 失败重试策略

| 重试次数 | 延迟 | 行为 |
|----------|------|------|
| 0 | - | 立即处理 |
| 1 | 1 分钟 | 简单重试 |
| 2 | 5 分钟 | 简单重试 |
| >= 3 | - | 标记为 `failed`，写入告警日志 |

### 4. 同步状态更新

```sql
-- 成功
UPDATE memory_sync_log
SET sync_status = 'synced',
    synced_at = NOW(),
    retry_count = retry_count + 1
WHERE id = $1;

-- 失败
UPDATE memory_sync_log
SET sync_status = 'failed',
    last_error = $2,
    retry_count = retry_count + 1
WHERE id = $1;
```

## 输出格式

### 执行报告
```json
{
  "run_id": "uuid",
  "trigger_type": "cron",
  "started_at": "2024-01-15T15:30:00Z",
  "completed_at": "2024-01-15T15:30:05Z",
  "duration_ms": 5123,
  "summary": {
    "total_pending": 23,
    "processed": 23,
    "successful": 22,
    "failed": 1,
    "skipped": 0
  },
  "tenant_breakdown": {
    "tenant-abc": {"processed": 10, "successful": 10},
    "tenant-xyz": {"processed": 13, "successful": 12, "failed": 1}
  },
  "failures": [
    {
      "signal_id": "uuid",
      "tenant_id": "tenant-xyz",
      "operation": "upsert_page",
      "error": "OpenAI API rate limit exceeded",
      "retry_count": 3
    }
  ]
}
```

### 监控指标
- `gbrain_sync_pending_total` — 当前待同步队列长度
- `gbrain_sync_processed_total` — 本次处理数量
- `gbrain_sync_failed_total` — 本次失败数量
- `gbrain_sync_latency_ms` — 平均处理延迟

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| MCP Adapter 未启动 | 跳过本次同步，记录告警；下次 cron 重试 |
| OpenAI API 限流 | 指数退避重试；超过 3 次标记失败 |
| 数据库连接失败 | 跳过本次，不影响其他信号；记录 job_runs 失败 |
| 单条信号处理失败 | 仅标记该条失败，继续处理后续 |
| 大批量处理超时 | 处理已读取的批次，剩余留到下次 cron |

## 数据库操作

- **memory_sync_log**：SELECT（读取待同步）、UPDATE（状态更新）
- **gbrain_pages**：INSERT / UPDATE（upsert_page）
- **gbrain_timeline_entries**：INSERT（add_timeline）
- **gbrain_links**：INSERT（create_link）
- **memory_entity_bridge**：UPDATE（sync_status）
- **job_runs**：INSERT（执行日志）

## 扩展计划

| 阶段 | 功能 |
|------|------|
| Phase 1 | 基础批量同步（当前） |
| Phase 2 | 实时同步（SyncQueue 直接触发） |
| Phase 3 | 冲突解决策略（last-write-wins / merge） |
| Phase 4 | 跨租户知识聚合（匿名化统计洞察） |
