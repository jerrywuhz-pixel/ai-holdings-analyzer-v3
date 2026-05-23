"""
Gateway Data Access Middleware — OpenClaw Skill 级数据访问层

提供强制 tenant_id 注入、Skill API Key 隔离、审计日志与配额检查。
任务生命周期管理（JobManager）、投递可靠性管理（DeliveryManager）、
Webhook 安全验证、记忆存储（gbrain MemoryMiddleware）集成。
"""

# 记忆模块导出（方便上层统一导入）
from openclaw.gateway.memory import (
    BrainOps,
    MCPClient,
    MemoryMiddleware,
    SignalDetector,
    SyncQueue,
)
from openclaw.gateway.confirmation_center import (
    ConfirmationCenterService,
    InMemoryConfirmationRepository,
    PendingActionInput,
    RoutingContext,
    SupabaseConfirmationRepository,
    build_confirmation_deep_link,
    classify_high_attention_text,
    interpret_voice_transcript,
    parse_confirmation_command,
)
from openclaw.gateway.confirmation_dispatcher import (
    ConfirmationPostDecisionDispatcher,
    InMemoryPostConfirmationTaskRepository,
    PostConfirmationTaskResult,
    SupabasePostConfirmationTaskRepository,
)
from openclaw.gateway.outbox import (
    DeliveryEnvelope,
    DeliveryOutboxService,
    DeliveryOutboxWorker,
    InMemoryOutboxRepository,
    LoggingDeliverySender,
    SlidingWindowRateLimiter,
    SupabaseOutboxRepository,
    is_within_quiet_hours,
)

__all__ = [
    "BrainOps",
    "MCPClient",
    "MemoryMiddleware",
    "SignalDetector",
    "SyncQueue",
    "ConfirmationCenterService",
    "InMemoryConfirmationRepository",
    "PendingActionInput",
    "RoutingContext",
    "SupabaseConfirmationRepository",
    "ConfirmationPostDecisionDispatcher",
    "InMemoryPostConfirmationTaskRepository",
    "PostConfirmationTaskResult",
    "SupabasePostConfirmationTaskRepository",
    "build_confirmation_deep_link",
    "classify_high_attention_text",
    "interpret_voice_transcript",
    "parse_confirmation_command",
    "DeliveryEnvelope",
    "DeliveryOutboxService",
    "DeliveryOutboxWorker",
    "InMemoryOutboxRepository",
    "LoggingDeliverySender",
    "SlidingWindowRateLimiter",
    "SupabaseOutboxRepository",
    "is_within_quiet_hours",
]
