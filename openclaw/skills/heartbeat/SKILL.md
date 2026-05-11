# Heartbeat Skill — 心跳巡检

## 触发条件

### Cron 定时触发
- OpenClaw cron 表达式：`*/5 * * * *`（每 5 分钟执行一次）
- 对应 task_definitions.name = `'heartbeat'`
- 系统级任务，无 tenant_id

### 手动触发
运维人员可通过管理接口强制执行心跳巡检：
- 管理命令：`heartbeat run`
- API 调用：`POST /api/admin/heartbeat`

## 输入格式

### 自动触发
由 cron 触发器传递：
```json
{
  "trigger_type": "cron",
  "task_name": "heartbeat"
}
```

无需外部输入，所有扫描逻辑由内部驱动。

## 处理逻辑

### 1. 创建自身 job_runs 记录
```
调用 JobManager.create_job("heartbeat") → 获取 heartbeat_job_id
调用 JobManager.start_job(heartbeat_job_id)
```

### 2. 扫描过期 PENDING job
```
查找 PENDING 状态超过 5 分钟的 job_runs：
- 调用 JobManager.find_stale_pending_jobs(stale_threshold_minutes=5)
- 对每个过期 PENDING job：
  → 标记 TIMED_OUT：JobManager.timeout_job(job_id)
  → 记录到 timed_out_jobs 列表
```

**判定逻辑**：
- `created_at < now() - 5 minutes` 且 `status = 'PENDING'`
- 可能原因：启动信号丢失、Worker 崩溃、调度器异常
- 处理方式：标记 TIMED_OUT，由 retry 机制重新调度

### 3. 扫描超时 RUNNING job
```
查找 RUNNING 状态超过 timeout_seconds 的 job_runs：
- 调用 JobManager.find_timed_out_running_jobs()
- 对每个超时 RUNNING job：
  → 标记 TIMED_OUT：JobManager.timeout_job(job_id)
  → 记录到 timed_out_jobs 列表
```

**判定逻辑**：
- `started_at + COALESCE(timeout_seconds, 120) < now()` 且 `status = 'RUNNING'`
- 可能原因：任务卡死、外部 API 无响应、死锁
- 处理方式：标记 TIMED_OUT，不自动重启（避免重复执行）

### 4. 扫描可重试的失败 delivery
```
查找 FAILED 且 retry_count < 3 的 delivery_runs：
- 调用 DeliveryManager.get_pending_retries(limit=50)
- 对每个可重试 delivery：
  → 重新触发推送（调用渠道发送接口）
  → 推送成功：DeliveryManager.mark_sent(delivery_id)
  → 推送失败：DeliveryManager.mark_failed(delivery_id, error)
  → 记录到 retried_deliveries 列表
```

**重试策略**：
- 首次失败后立即重试（heartbeat 第 1 次扫描到）
- 后续失败等待下一次 heartbeat 间隔（5 分钟）
- 最多重试 3 次

### 5. 标记超过最大重试的 delivery 为 ABANDONED
```
查找 retry_count >= 3 且仍为 FAILED 的 delivery_runs：
- 调用 DeliveryManager.get_abandonable_deliveries()
- 对每个超限 delivery：
  → 标记 ABANDONED：DeliveryManager.mark_abandoned(delivery_id)
  → 记录到 abandoned_deliveries 列表
```

### 6. 完成自身 job_runs 记录
```
调用 JobManager.complete_job(heartbeat_job_id, result=HeartbeatReport)
```

## 输出格式

### HeartbeatReport
```json
{
  "timed_out_jobs": [
    {
      "job_id": "uuid",
      "job_type": "daily_analysis",
      "previous_status": "PENDING",
      "stale_duration_seconds": 420
    }
  ],
  "retried_deliveries": [
    {
      "delivery_id": "uuid",
      "job_run_id": "uuid",
      "channel": "wechat_claw",
      "retry_attempt": 2,
      "retry_result": "sent"
    }
  ],
  "abandoned_deliveries": [
    {
      "delivery_id": "uuid",
      "retry_count": 3,
      "error_message": "Connection refused after 3 retries"
    }
  ],
  "scan_summary": {
    "pending_scanned": 12,
    "running_scanned": 8,
    "deliveries_scanned": 25,
    "total_actions_taken": 5
  }
}
```

### 日志输出
```
[heartbeat] Scan started at 2024-01-15T15:00:00Z
[heartbeat] Found 2 stale PENDING jobs → marked TIMED_OUT
[heartbeat] Found 1 timed-out RUNNING jobs → marked TIMED_OUT
[heartbeat] Found 3 retriable deliveries → retried (2 sent, 1 failed)
[heartbeat] Found 1 abandonable deliveries → marked ABANDONED
[heartbeat] Scan completed in 1.2s
```

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| Supabase 查询失败 | 跳过当前扫描步骤，继续下一步骤；记录错误到 job_runs.error_message |
| 单个 job 标记失败 | 跳过该 job，继续处理其余；将失败信息加入 HeartbeatReport |
| delivery 重试推送失败 | mark_failed 递增 retry_count；不超过 3 次则下次 heartbeat 再试 |
| delivery 重试推送异常 | 捕获异常，不阻断其余 delivery 处理 |
| 自身 job 创建失败 | 记录错误日志，退出；等待下次 cron 触发 |
| 自身 job 超过 60 秒 | 由下一个 heartbeat 实例标记 TIMED_OUT |
| 数据库连接池耗尽 | 降级：仅扫描 job_runs（优先级更高），跳过 delivery 重试 |

## 示例

### 示例 1：正常心跳巡检（发现超时 job）
```
[cron 15:00 触发]

系统：Heartbeat scan started...
      Scanning job_runs:
        - 2 PENDING jobs older than 5min → TIMED_OUT
        - 1 RUNNING job exceeded 120s → TIMED_OUT
      Scanning delivery_runs:
        - 3 FAILED deliveries with retry_count < 3 → retrying...
        - 2 sent successfully, 1 still failed (retry_count now 2)
      No abandonable deliveries.
      
      HeartbeatReport:
      timed_out_jobs: 3, retried_deliveries: 3, abandoned_deliveries: 0
```

### 示例 2：无异常的心跳巡检
```
[cron 15:05 触发]

系统：Heartbeat scan started...
      Scanning job_runs:
        - 0 stale PENDING jobs
        - 0 timed-out RUNNING jobs
      Scanning delivery_runs:
        - 0 retriable deliveries
      
      HeartbeatReport:
      timed_out_jobs: 0, retried_deliveries: 0, abandoned_deliveries: 0
      All systems healthy.
```

### 示例 3：delivery 超过最大重试次数
```
[cron 15:10 触发]

系统：Heartbeat scan started...
      Scanning delivery_runs:
        - 1 FAILED delivery with retry_count=3 → ABANDONED
        - 1 FAILED delivery with retry_count=2 → retrying...
        - retry failed (retry_count now 3)
      
      Next heartbeat will mark the newly failed one as ABANDONED.
      
      HeartbeatReport:
      timed_out_jobs: 0, retried_deliveries: 1, abandoned_deliveries: 1
```

## 数据库操作

- **job_runs**：SELECT（扫描 PENDING / RUNNING），UPDATE（标记 TIMED_OUT），INSERT（自身执行记录）
- **delivery_runs**：SELECT（扫描 FAILED 可重试），UPDATE（标记 SENT / FAILED / ABANDONED）
- **task_definitions**：SELECT（查找 heartbeat 任务配置）

## 扩展计划

| 阶段 | 功能 |
|------|------|
| Phase 4.1 | 基础心跳巡检（当前） |
| Phase 4.2 | 智能重试策略（指数退避 + 优先级队列） |
| Phase 4.3 | 告警集成（连续失败 > 阈值时推送运维告警） |
| Phase 4.4 | 自适应扫描频率（空闲时降低频率，异常时提高频率） |
