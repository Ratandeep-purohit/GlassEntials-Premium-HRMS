from django.http import HttpResponse
from django.template import engines


ERROR_CONFIG = {
    400: {
        "eyebrow": "Bad Request",
        "title": "This request could not be processed",
        "message": "The page received information it could not understand. Please go back and try again.",
        "tone": "warning",
    },
    403: {
        "eyebrow": "Access Restricted",
        "title": "You do not have permission",
        "message": "Your account does not have access to this area. Contact HR/Admin if this looks incorrect.",
        "tone": "warning",
    },
    404: {
        "eyebrow": "Page Not Found",
        "title": "This page is not available",
        "message": "The link may be old, moved, or typed incorrectly.",
        "tone": "info",
    },
    500: {
        "eyebrow": "System Error",
        "title": "Something went wrong",
        "message": "The system hit an unexpected error. Your data is protected, and the issue has been logged.",
        "tone": "danger",
    },
}


def _default_action(request):
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return "/home/", "Back to Dashboard"
    return "/login/", "Back to Login"


def _render_error_page(request, status_code, **overrides):
    config = {**ERROR_CONFIG.get(status_code, ERROR_CONFIG[500]), **overrides}
    action_url, action_label = _default_action(request)
    template = engines["django"].get_template("errors/error_page.html")
    html = template.render({
        "status_code": status_code,
        "eyebrow": config["eyebrow"],
        "title": config["title"],
        "message": config["message"],
        "tone": config["tone"],
        "action_url": action_url,
        "action_label": action_label,
    })
    return HttpResponse(html, status=status_code)


def bad_request(request, exception=None):
    return _render_error_page(request, 400)


def permission_denied(request, exception=None):
    return _render_error_page(request, 403)


def page_not_found(request, exception=None):
    return _render_error_page(request, 404)


def server_error(request):
    return _render_error_page(request, 500)


def csrf_failure(request, reason=""):
    return _render_error_page(
        request,
        403,
        eyebrow="Session Verification Failed",
        title="Please refresh and try again",
        message="For security, the form session expired or could not be verified. Refresh the page, then submit again.",
        tone="warning",
    )
