"""Shared material-index response for document and navigation mutations."""

def qmds_payload(config, document_service) -> dict:
    return {
        "root": str(config.root),
        "qmds": document_service.all_entries(),
        "warnings": document_service.qmd_warnings(),
        "rootTags": document_service.root_tags(),
        "tagParents": document_service.tag_parents(),
    }

