"""search_product tool -- search products by keyword and optional category."""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult

from open_chat_shop.tools.builtin._mock_data import PRODUCTS


class SearchProductTool(BaseTool):
    """Search the product catalog by keyword and optional category filter."""

    name: str = "search_product"
    description: str = "Search products by keyword. Optionally filter by category and limit results."
    category: str = "product"
    params_schema: dict[str, Any] = {
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

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        keyword = params["keyword"].lower()
        category = params.get("category")
        limit = params.get("limit", 5)

        results = []
        for product in PRODUCTS:
            if keyword not in product["name"].lower():
                continue
            if category and product["category"] != category:
                continue
            results.append({
                "id": product["id"],
                "name": product["name"],
                "price": product["price"],
                "image_url": product["image_url"],
            })
            if len(results) >= limit:
                break

        return ToolResult(
            success=True,
            data={"products": results, "total_found": len(results)},
        )
