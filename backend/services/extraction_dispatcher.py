"""Choose a document-specific extractor without a central type-to-module map."""

from dataclasses import dataclass
from importlib import import_module


from services.classifier import UNKNOWN_DOCUMENT_TYPE


@dataclass(frozen=True)
class ExtractionResult:
    """Fields returned by the selected extractor and its module name."""

    fields: dict[str, str]
    extractor_name: str


def extract_document_fields(document_type: str, ocr_text: str) -> ExtractionResult:
    """Load the conventionally named extractor for a classified document.

    For example, `Income Certificate` uses
    `services.extractors.income_certificate`. Adding a document type therefore
    needs only one classifier rule and one matching extractor file.
    """
    extractor_name = document_type_to_module_name(document_type)
    if document_type == UNKNOWN_DOCUMENT_TYPE:
        extractor_name = "generic"

    try:
        module = import_module(f"services.extractors.{extractor_name}")
    except ModuleNotFoundError as error:
        if error.name != f"services.extractors.{extractor_name}":
            raise
        extractor_name = "generic"
        module = import_module("services.extractors.generic")

    return ExtractionResult(module.extract_fields(ocr_text), extractor_name)


def document_type_to_module_name(document_type: str) -> str:
    """Convert a display name such as `Birth Certificate` to a module name."""
    return "_".join(document_type.lower().split())
