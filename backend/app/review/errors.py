"""
P4 - Standard Error Responses

All API errors follow this structure:
{
    "error_code": "TICKET_NOT_FOUND",
    "message": "Ticket not found",
    "detail": {}
}
"""

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class ReviewError:
    REVIEW_NOT_FOUND = "REVIEW_NOT_FOUND"
    TICKET_NOT_FOUND = "TICKET_NOT_FOUND"
    REPORT_NOT_FOUND = "REPORT_NOT_FOUND"
    INVALID_REVIEW_TYPE = "INVALID_REVIEW_TYPE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    INVALID_VERSION_TAG = "INVALID_VERSION_TAG"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


ERROR_MESSAGES = {
    ReviewError.REVIEW_NOT_FOUND: "Review payload not found",
    ReviewError.TICKET_NOT_FOUND: "Ticket not found",
    ReviewError.REPORT_NOT_FOUND: "Report version not found",
    ReviewError.INVALID_REVIEW_TYPE: "Invalid review type",
    ReviewError.APPROVAL_REQUIRED: "Pharmacist approval required",
    ReviewError.INVALID_VERSION_TAG: "Invalid report version",
    ReviewError.INTERNAL_SERVER_ERROR: "Internal server error",
}

STATUS_CODES = {
    ReviewError.REVIEW_NOT_FOUND: 404,
    ReviewError.TICKET_NOT_FOUND: 404,
    ReviewError.REPORT_NOT_FOUND: 404,
    ReviewError.INVALID_REVIEW_TYPE: 422,
    ReviewError.APPROVAL_REQUIRED: 403,
    ReviewError.INVALID_VERSION_TAG: 422,
    ReviewError.INTERNAL_SERVER_ERROR: 500,
}


def raise_review_error(error_code: str, detail: dict = {}) -> None:
    """
    표준 에러 응답 형식으로 HTTPException 발생.

    예시:
        raise_review_error(ReviewError.TICKET_NOT_FOUND)
        raise_review_error(ReviewError.REPORT_NOT_FOUND, {"ticket_id": "T-001"})
    """
    raise HTTPException(
        status_code=STATUS_CODES.get(error_code, 500),
        detail={
            "error_code": error_code,
            "message": ERROR_MESSAGES.get(error_code, "Unknown error"),
            "detail": detail,
        },
    )
