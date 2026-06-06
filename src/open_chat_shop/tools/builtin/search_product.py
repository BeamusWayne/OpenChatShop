"""search_product tool -- search products by keyword and optional category."""

from __future__ import annotations

from typing import Any, ClassVar

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult
from open_chat_shop.storage.repositories.abc import ProductRepository
from open_chat_shop.storage.repositories.memory import InMemoryProductRepository


class SearchProductTool(BaseTool):
    """Search the product catalog by keyword and optional category filter."""

    name: str = "search_product"
    description: str = (
        "Search products by keyword. Optionally filter by category "
        "and limit results."
    )
    category: str = "product"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "Search keyword"},
            "category": {"type": "string", "description": "Optional category filter"},
            "limit": {"type": "integer", "description": "Max results to return", "default": 5},
        },
        "required": ["keyword"],
        "additionalProperties": False,
    }
    permissions: ToolPermission = ToolPermission(
        required_roles=["customer"],
        idempotent=True,
    )

    def __init__(self, product_repo: ProductRepository | None = None) -> None:
        self._product_repo = product_repo or InMemoryProductRepository()

    async def execute(self, params: dict[str, Any], context: SessionContext) -> ToolResult:
        keyword = params["keyword"]
        category = params.get("category")
        limit = params.get("limit", 5)

        results = self._product_repo.search(keyword, category, limit)

        return ToolResult(
            success=True,
            data={"products": results, "total_found": len(results)},
        )

    def format_result(self, result: ToolResult) -> str:
        data = result.data
        if not data:
            return "操作成功"
        products = data.get("products", [])
        if not products:
            return "未找到相关商品，请尝试其他关键词。"
        lines = [f"为您找到 {data.get('total_found', len(products))} 件商品："]
        for p in products:
            lines.append(f"  - {p['name']}  ¥{p['price']:.2f}")
        return "\n".join(lines)
