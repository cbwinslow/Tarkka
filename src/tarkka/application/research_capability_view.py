"""Transport-neutral JSON views for staged Tarkka research capability discovery."""

from __future__ import annotations

from tarkka.application.research_capabilities import (
    ResearchCapabilities,
    ResearchOperationSchema,
    research_capabilities,
)


def research_capabilities_view(
    capabilities: ResearchCapabilities | None = None,
) -> dict[str, object]:
    """Serialize the compact first-stage capability index without transport decoration."""
    index = capabilities if capabilities is not None else research_capabilities()
    return {
        "version": index.version,
        "estimated_tokens": index.estimated_tokens,
        "operations": [
            {
                "operation_id": operation.operation_id,
                "family": operation.family,
                "summary": operation.summary,
                "estimated_tokens": operation.estimated_tokens,
            }
            for operation in index.operations
        ],
    }


def research_operation_schema_view(schema: ResearchOperationSchema) -> dict[str, object]:
    """Serialize one selected operation descriptor without implementation types."""
    operation = schema.operation
    return {
        "operation": {
            "operation_id": operation.operation_id,
            "family": operation.family,
            "summary": operation.summary,
            "estimated_tokens": operation.estimated_tokens,
        },
        "inputs": [
            {
                "name": field.name,
                "value_type": field.value_type,
                "required": field.required,
                "summary": field.summary,
                "allowed_values": list(field.allowed_values),
                "item_value_type": field.item_value_type,
                "property_value_type": field.property_value_type,
                "minimum": field.minimum,
                "maximum": field.maximum,
                "required_when": field.required_when,
            }
            for field in schema.inputs
        ],
        "result_summary": schema.result_summary,
        "estimated_tokens": schema.estimated_tokens,
    }
