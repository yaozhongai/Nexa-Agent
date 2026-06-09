"""
VLM 视觉语言模型管线接口 — 路线 B

提供 VLM 端到端识别的抽象接口，不包含具体实现（非 mock）。
下游调用方依赖此接口编程，实际 VLM 模型在后续接入（MiniCPM-V / Qwen-VL）。

日志统一使用 logger_config.get_logger。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger_config import get_logger

logger = get_logger("vlm_pipeline")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class VLMResult:
    """VLM 识别结果"""
    response: str = ""                         # 模型自然语言回答
    structured_data: Dict[str, Any] = field(default_factory=dict)  # 结构化抽取结果
    confidence: float = 0.0
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: float = 0.0
    raw_output: str = ""                       # 模型原始输出（调试用）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response": self.response,
            "structured_data": self.structured_data,
            "confidence": self.confidence,
            "model_name": self.model_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "elapsed_ms": self.elapsed_ms,
        }


# ---------------------------------------------------------------------------
# VLM 接口
# ---------------------------------------------------------------------------

class BaseVLMEngine(ABC):
    """VLM 引擎抽象基类

    子类需实现 analyze_image() 方法。
    当前阶段仅定义接口，不做 mock 实现。
    """

    @abstractmethod
    def analyze_image(
        self,
        image_path: str,
        prompt: str = "",
        **kwargs,
    ) -> VLMResult:
        """对图片进行端到端理解

        Args:
            image_path: 图片文件路径
            prompt: 引导提示词。若为空则使用默认 prompt
            **kwargs: 引擎特定参数

        Returns:
            VLMResult
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查引擎是否可用"""
        ...


# ---------------------------------------------------------------------------
# VLM Prompt 模板
# ---------------------------------------------------------------------------

INVOICE_EXTRACTION_PROMPT = """你是一个专业的票据识别助手。请分析这张票据图片，提取以下信息并以 JSON 格式返回：

{
    "invoice_code": "发票号码",
    "invoice_date": "开票日期 (YYYY-MM-DD)",
    "amount": "金额（数字，不含单位）",
    "tax_number": "税号",
    "seller_name": "销售方名称",
    "buyer_name": "购买方名称",
    "items": [
        {"name": "商品名称", "quantity": "数量", "unit_price": "单价", "amount": "金额"}
    ],
    "notes": "备注或补充信息"
}

注意：
- 若某项信息无法识别，填写空字符串或 null
- 确保金额为纯数字
- 日期统一为 YYYY-MM-DD 格式"""

GENERAL_IMAGE_PROMPT = """请详细描述这张图片的内容，包括：
1. 图片中有什么？
2. 关键的文字信息
3. 图片的整体布局和结构

如果图片中包含表格，请以结构化方式呈现。"""
